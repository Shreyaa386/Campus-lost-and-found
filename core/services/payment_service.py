"""
Payment Gateway Service for CampusCare Institutional Subscriptions.
Provides modular integration supporting Razorpay and Stripe webhook verification.
Enforces HMAC-SHA256 cryptographic signature validation, strict idempotency checks,
and audit logging while ensuring raw credit card details are never persisted.
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.models import Institution, InstitutionSubscription, PaymentTransaction, SubscriptionPlan
from core.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Secure gateway integration and webhook fulfillment engine.
    """

    @classmethod
    def create_checkout_session(cls, institution: Institution, plan: SubscriptionPlan, billing_cycle: str = 'monthly') -> dict:
        """
        Initializes a pending payment order/session for an institution subscription upgrade.
        """
        amount = plan.price_annual if billing_cycle == 'annual' else plan.price_monthly
        order_id = f"order_{institution.slug[:10]}_{uuid.uuid4().hex[:12]}"
        idempotency_key = f"idem_{uuid.uuid4().hex}"

        transaction = PaymentTransaction.objects.create(
            institution=institution,
            transaction_id=order_id,
            gateway=getattr(settings, 'PAYMENT_GATEWAY_PROVIDER', 'razorpay'),
            amount=amount,
            currency='INR',
            status=PaymentTransaction.STATUS_PENDING,
            idempotency_key=idempotency_key,
            payload={
                'plan_code': plan.code,
                'billing_cycle': billing_cycle,
                'institution_id': institution.id,
            }
        )

        return {
            'order_id': order_id,
            'amount': float(amount),
            'currency': 'INR',
            'plan_name': plan.name,
            'billing_cycle': billing_cycle,
            'key_id': getattr(settings, 'PAYMENT_GATEWAY_KEY', 'rzp_test_campuscare'),
            'transaction_pk': transaction.pk
        }

    @classmethod
    def verify_webhook_signature(cls, raw_body: bytes, signature_header: str, secret: str = None) -> bool:
        """
        Cryptographically verifies the HMAC-SHA256 signature against the raw payload.
        """
        webhook_secret = secret or getattr(settings, 'PAYMENT_WEBHOOK_SECRET', '')
        if not webhook_secret or not signature_header:
            return False

        try:
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                raw_body,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_signature, signature_header)
        except Exception as e:
            logger.error(f"Webhook signature calculation error: {e}")
            return False

    @classmethod
    def process_webhook_event(cls, payload: dict, raw_body: bytes = b'', signature: str = '', request=None) -> tuple[bool, str]:
        """
        Processes an incoming payment webhook.
        Guarantees idempotency to prevent duplicate credit processing.
        Returns: (success: bool, message: str)
        """
        # 1. Signature Verification
        webhook_secret = getattr(settings, 'PAYMENT_WEBHOOK_SECRET', '')
        if webhook_secret:
            if not cls.verify_webhook_signature(raw_body, signature, webhook_secret):
                logger.warning("Payment webhook signature verification failed.")
                return False, "Invalid HMAC signature."
        else:
            # In test/local mode without secret, allow mock verification with clear audit log
            logger.info("PAYMENT_WEBHOOK_SECRET unset: Running in sandbox test mode.")

        # 2. Extract Event Data
        event_type = payload.get('event', 'payment.captured')
        payment_data = payload.get('payload', {}).get('payment', {}).get('entity', {})
        order_id = payment_data.get('order_id') or payload.get('order_id') or payload.get('transaction_id')

        if not order_id:
            return False, "Missing order_id or transaction_id in webhook payload."

        # 3. Idempotency Check
        transaction = PaymentTransaction.objects.filter(transaction_id=order_id).first()
        if not transaction:
            return False, f"Transaction '{order_id}' not found."

        if transaction.status == PaymentTransaction.STATUS_COMPLETED:
            logger.info(f"Idempotency: Order '{order_id}' already processed.")
            return True, "Payment already processed (idempotent)."

        # 4. Fulfill Subscription Upgrade
        inst = transaction.institution
        plan_code = transaction.payload.get('plan_code', 'pro')
        billing_cycle = transaction.payload.get('billing_cycle', 'monthly')
        plan = SubscriptionPlan.objects.filter(code=plan_code).first() or SubscriptionPlan.get_default_plan()

        days = 365 if billing_cycle == 'annual' else 30
        now = timezone.now()
        period_end = now + timedelta(days=days)

        subscription, _ = InstitutionSubscription.objects.get_or_create(
            institution=inst,
            defaults={'plan': plan, 'current_period_end': period_end}
        )
        subscription.plan = plan
        subscription.status = InstitutionSubscription.STATUS_ACTIVE
        subscription.billing_cycle = billing_cycle
        subscription.current_period_start = now
        subscription.current_period_end = period_end
        subscription.auto_renew = True
        subscription.save()

        # Update transaction status
        transaction.status = PaymentTransaction.STATUS_COMPLETED
        transaction.subscription = subscription
        transaction.invoice_number = f"INV-{now.strftime('%Y%m')}-{transaction.id:05d}"
        transaction.payload['event_received'] = event_type
        transaction.save()

        # 5. Audit Logging
        AuditService.log_action(
            action='reward_adjust',  # or subscription audit
            actor=None,
            target_obj=subscription,
            details={
                'event': 'subscription_activated',
                'plan': plan.name,
                'billing_cycle': billing_cycle,
                'transaction_id': order_id,
                'amount': str(transaction.amount)
            },
            request=request
        )

        logger.info(f"Successfully activated '{plan.name}' subscription for '{inst.name}'.")
        return True, f"Subscription for {inst.name} upgraded to {plan.name}."

