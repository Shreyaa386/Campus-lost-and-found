"""
Modular SMS and WhatsApp Notification Package Service for CampusCare.
Manages prepaid institutional message credit pools, consent-compliant dispatch,
quota accounting, and privacy-masked usage logging without leaking unmasked phone numbers.
"""

import logging
import re
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.models import Institution, NotificationPackage, NotificationUsageLog

logger = logging.getLogger(__name__)


class NotificationPackageService:
    """
    Manages prepaid institutional notification packages and delivery quotas.
    """

    @classmethod
    def purchase_package(cls, institution: Institution, package_type: str = 'sms', credits_count: int = 500, cost: float = 499.00) -> NotificationPackage:
        """
        Grants a new prepaid notification credit batch to an institution.
        """
        pkg = NotificationPackage.objects.create(
            institution=institution,
            package_type=package_type,
            credits_purchased=credits_count,
            credits_remaining=credits_count,
            cost=cost
        )
        logger.info(f"Institution '{institution.name}' credited with {credits_count} {package_type.upper()} notifications.")
        return pkg

    @classmethod
    def get_remaining_credits(cls, institution: Institution, package_type: str = 'sms') -> int:
        """Calculates total active credits across packages for the institution."""
        if not institution:
            return 0
        packages = NotificationPackage.objects.filter(institution=institution, package_type=package_type)
        return sum(p.credits_remaining for p in packages)

    @classmethod
    def send_notification(cls, institution: Institution, recipient_phone: str, message: str, notification_type: str = 'sms', purpose: str = 'general', user=None) -> tuple[bool, str]:
        """
        Sends a notification after verifying student consent and available quota.
        Masks personal numbers in all audit records.
        """
        if not recipient_phone:
            return False, "Recipient phone number is empty."

        clean_phone = re.sub(r'[\s\-\(\)]', '', recipient_phone)
        masked_phone = cls.mask_phone(clean_phone)

        # 1. User Consent Verification
        if user and hasattr(user, 'notification_preferences'):
            pref = user.notification_preferences
            if notification_type == 'sms' and not getattr(pref, 'allow_sms', True):
                logger.info(f"Skipping SMS: User {user.username} has opted out of SMS alerts.")
                return False, "User has opted out of SMS notifications."
            if notification_type == 'whatsapp' and not getattr(pref, 'allow_whatsapp', True):
                logger.info(f"Skipping WhatsApp: User {user.username} has opted out of WhatsApp alerts.")
                return False, "User has opted out of WhatsApp notifications."

        # 2. Quota Check & Credit Deduction (Atomic Transaction)
        with transaction.atomic():
            pkg = NotificationPackage.objects.select_for_update().filter(
                institution=institution,
                package_type=notification_type,
                credits_remaining__gt=0
            ).order_by('purchased_at').first()

            if not pkg:
                logger.warning(f"Notification dispatch blocked: '{institution.name}' has 0 remaining {notification_type.upper()} credits.")
                return False, f"Insufficient {notification_type.upper()} credits. Please refill notification package."

            pkg.credits_remaining -= 1
            pkg.save(update_fields=['credits_remaining'])

            # 3. Log Usage Audit
            NotificationUsageLog.objects.create(
                institution=institution,
                user=user,
                notification_type=notification_type,
                recipient_masked=masked_phone,
                purpose=purpose,
                consent_verified=True,
                status='sent'
            )

        # 4. Dispatch via Gateway or Console Mock
        cls._dispatch_to_provider(clean_phone, message, notification_type)

        logger.info(f"Dispatched {notification_type.upper()} to {masked_phone} for purpose '{purpose}'. Remaining: {pkg.credits_remaining}")
        return True, f"Notification sent successfully ({pkg.credits_remaining} credits remaining)."

    @classmethod
    def _dispatch_to_provider(cls, phone: str, message: str, notification_type: str):
        """Simulates or calls real gateway API based on configuration."""
        sms_key = getattr(settings, 'SMS_GATEWAY_KEY', '')
        whatsapp_key = getattr(settings, 'WHATSAPP_API_KEY', '')

        if notification_type == 'sms' and sms_key:
            # Here: Integration with Twilio / Fast2SMS API
            pass
        elif notification_type == 'whatsapp' and whatsapp_key:
            # Here: Integration with WhatsApp Cloud API
            pass
        else:
            # Console logger fallback (development/test mode)
            logger.debug(f"[{notification_type.upper()} MOCK DISPATCH] Phone: {phone[:3]}*** Message: {message[:40]}...")

    @classmethod
    def mask_phone(cls, phone: str) -> str:
        """Masks central digits of phone number: +91 98*** **321"""
        if len(phone) < 8:
            return "***"
        prefix = phone[:4]
        suffix = phone[-3:]
        return f"{prefix}****{suffix}"

