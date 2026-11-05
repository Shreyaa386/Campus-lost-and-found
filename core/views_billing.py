"""
Subscription Plans, Payment Gateway Checkout, and Multi-Institution Analytics Views.
Handles tier upgrades, checkout initialization, cryptographic webhook verification,
and cross-college recovery comparisons.
"""

import json
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.models import Institution, InstitutionSubscription, PaymentTransaction, SubscriptionPlan
from core.services.payment_service import PaymentService
from core.views_admin import staff_or_admin_required

logger = logging.getLogger(__name__)


@login_required
def subscription_plans_view(request):
    """
    Displays subscription tiers, active institution plan, and feature matrix.
    """
    institution = getattr(request, 'institution', None) or getattr(request.user, 'institution', None)
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('price_monthly')
    current_sub = getattr(institution, 'subscription', None) if institution else None

    # Guarantee default plan exists
    if not plans.exists():
        SubscriptionPlan.get_default_plan()
        plans = SubscriptionPlan.objects.filter(is_active=True)

    return render(request, 'billing/plans.html', {
        'institution': institution,
        'plans': plans,
        'current_sub': current_sub,
    })


@login_required
@staff_or_admin_required
def initiate_checkout_view(request, plan_code):
    """
    Initializes a checkout session with the payment gateway for an institution upgrade.
    """
    institution = getattr(request, 'institution', None) or getattr(request.user, 'institution', None)
    if not institution:
        messages.error(request, "No active campus institution associated with your account.")
        return redirect('subscription_plans')

    plan = get_object_or_404(SubscriptionPlan, code=plan_code, is_active=True)
    billing_cycle = request.GET.get('cycle', 'monthly')

    if plan.code == 'free' or (plan.price_monthly == 0 and plan.price_annual == 0):
        # Immediate free tier assignment
        sub, _ = InstitutionSubscription.objects.get_or_create(
            institution=institution,
            defaults={'plan': plan, 'current_period_end': timezone.now() + timezone.timedelta(days=365)}
        )
        sub.plan = plan
        sub.status = InstitutionSubscription.STATUS_ACTIVE
        sub.save()
        messages.success(request, f"Institution '{institution.name}' assigned to Campus Starter (Free) plan.")
        return redirect('subscription_plans')

    session_data = PaymentService.create_checkout_session(
        institution=institution,
        plan=plan,
        billing_cycle=billing_cycle
    )

    return render(request, 'billing/checkout.html', {
        'institution': institution,
        'plan': plan,
        'session_data': session_data,
        'billing_cycle': billing_cycle,
    })


@csrf_exempt
@require_POST
def payment_webhook_view(request):
    """
    Cryptographically verified webhook listener for Razorpay / Stripe payment capture events.
    Verifies HMAC-SHA256 signature and applies idempotent subscription upgrades.
    """
    raw_body = request.body
    signature = request.headers.get('X-Razorpay-Signature') or request.headers.get('Stripe-Signature') or ''

    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except Exception:
        logger.warning("Received invalid JSON payload on payment webhook.")
        return HttpResponseBadRequest("Malformed JSON.")

    success, message = PaymentService.process_webhook_event(
        payload=payload,
        raw_body=raw_body,
        signature=signature,
        request=request
    )

    if success:
        return JsonResponse({'status': 'ok', 'message': message})
    else:
        logger.warning(f"Payment webhook rejected: {message}")
        return HttpResponseBadRequest(message)


@staff_or_admin_required
def multi_institution_analytics_view(request):
    """
    Executive Multi-Campus Comparison & Platform Analytics.
    Compares active reports, recovery rates, and subscription utilization across institutions.
    """
    from items.models import Item, Claim
    institutions = Institution.objects.filter(is_active=True).select_related('subscription', 'subscription__plan')

    comparison_data = []
    total_platform_items = 0
    total_platform_recovered = 0

    for inst in institutions:
        inst_items = Item.objects.filter(institution=inst)
        total_items = inst_items.count()
        recovered = inst_items.filter(status=Item.STATUS_RETURNED).count()
        rate = round((recovered / total_items * 100), 1) if total_items > 0 else 0.0

        total_platform_items += total_items
        total_platform_recovered += recovered

        plan_name = inst.subscription.plan.name if hasattr(inst, 'subscription') and inst.subscription.plan else "Campus Starter (Free)"
        sub_status = inst.subscription.get_status_display() if hasattr(inst, 'subscription') else "Active (Default)"

        comparison_data.append({
            'institution': inst,
            'total_items': total_items,
            'recovered_items': recovered,
            'recovery_rate': rate,
            'plan_name': plan_name,
            'sub_status': sub_status,
            'custom_domain': inst.custom_domain or "Default Subdomain",
            'is_federated': inst.is_federated_search_enabled
        })

    platform_recovery_rate = round((total_platform_recovered / total_platform_items * 100), 1) if total_platform_items > 0 else 0.0

    return render(request, 'dashboard/institution_analytics.html', {
        'comparison_data': comparison_data,
        'total_institutions': institutions.count(),
        'total_platform_items': total_platform_items,
        'total_platform_recovered': total_platform_recovered,
        'platform_recovery_rate': platform_recovery_rate,
    })

