"""
Administrator and Campus Security Dashboard Views for CampusCare.
Provides centralized monitoring, user management, item & category governance,
claim moderation, security alerts, audit logging, analytics, heatmaps, and report exports.
"""

from functools import wraps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from core.forms_admin import (
    CampusLocationForm,
    CategoryForm,
    ReportExportFilterForm,
    SecurityAlertReviewForm,
    UserRoleUpdateForm,
)
from core.models import AuditLog, CampusLocation, Category, SecurityAlert
from core.services import (
    AnalyticsService,
    AuditService,
    HeatmapService,
    PredictionService,
    ReportExportService,
    SecurityMonitoringService,
)
from items.models import Claim, ClaimStatusHistory, Handover, Item, ItemStatusHistory, RewardTransaction
from items.services import NotificationService

User = get_user_model()


def staff_or_admin_required(view_func):
    """Restricts access to campus staff members and system administrators."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not getattr(request.user, 'is_staff_member', False):
            raise PermissionDenied("Access restricted to Campus Staff and Administrators only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def admin_only_required(view_func):
    """Restricts high-privilege operations strictly to Administrators."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not getattr(request.user, 'is_admin_user', False):
            raise PermissionDenied("This administrative action requires Administrator privileges.")
        return view_func(request, *args, **kwargs)
    return _wrapped


# --------------------------------------------------------------------------
# 1. EXECUTIVE DASHBOARD OVERVIEW
# --------------------------------------------------------------------------

@staff_or_admin_required
def dashboard_overview_view(request):
    """
    Main Administrator & Campus Security Dashboard Overview.
    Displays live KPI metrics, active security alerts, recent audit entries,
    and monthly recovery performance.
    """
    institution = request.user.institution

    # Auto-sync real-time security alerts
    SecurityMonitoringService.sync_security_alerts(institution)

    kpis = AnalyticsService.get_kpis(institution)
    alerts_summary = SecurityMonitoringService.get_alerts_summary(institution)

    # Top active alerts
    active_alerts = (
        SecurityAlert.objects.filter(status=SecurityAlert.STATUS_PENDING)
        .select_related('user', 'item', 'claim')[:5]
    )

    # Recent audit trail
    recent_audits = (
        AuditLog.objects.all().select_related('actor')[:6]
    )

    # Monthly trends for chart
    monthly_trends = AnalyticsService.get_monthly_trends(institution, months_count=6)

    # Unclaimed found items older than 7 days
    seven_days_ago = timezone.now() - timezone.timedelta(days=7)
    unclaimed_sample = (
        Item.objects.filter(report_type=Item.REPORT_TYPE_FOUND, status=Item.STATUS_OPEN, created_at__lte=seven_days_ago)
        .select_related('category', 'location')[:5]
    )

    return render(request, 'dashboard/overview.html', {
        'kpis': kpis,
        'alerts_summary': alerts_summary,
        'active_alerts': active_alerts,
        'recent_audits': recent_audits,
        'monthly_trends': monthly_trends,
        'unclaimed_sample': unclaimed_sample,
    })


# --------------------------------------------------------------------------
# 2. USER MANAGEMENT
# --------------------------------------------------------------------------

@staff_or_admin_required
def user_list_view(request):
    """Search, filter, and view campus student, faculty, and staff profiles."""
    users_qs = User.objects.all().select_related('institution', 'department').order_by('-date_joined')
    if not request.user.is_superuser and request.user.institution:
        users_qs = users_qs.filter(institution=request.user.institution)

    # Search query
    q = request.GET.get('q', '').strip()
    if q:
        users_qs = users_qs.filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(email__icontains=q) |
            Q(student_id__icontains=q)
        )

    # Filters
    role_filter = request.GET.get('role', '')
    if role_filter:
        users_qs = users_qs.filter(role=role_filter)

    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        users_qs = users_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        users_qs = users_qs.filter(is_active=False)

    paginator = Paginator(users_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'dashboard/users.html', {
        'page_obj': page_obj,
        'q': q,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'roles': User.ROLE_CHOICES,
    })


@staff_or_admin_required
def user_detail_view(request, user_id):
    """Detailed profile of a campus user with audit history, reports, and rewards."""
    target_user = get_object_or_404(User.objects.select_related('institution', 'department'), pk=user_id)

    reports = Item.objects.filter(user=target_user).select_related('category', 'location')[:10]
    claims = Claim.objects.filter(claimant=target_user).select_related('item')[:10]
    rewards = RewardTransaction.objects.filter(user=target_user)[:10]
    alerts = SecurityAlert.objects.filter(user=target_user)[:5]
    audit_history = AuditLog.objects.filter(
        Q(actor=target_user) | Q(target_model='User', target_object_id=str(target_user.pk))
    )[:8]

    role_form = UserRoleUpdateForm(instance=target_user, actor=request.user)

    return render(request, 'dashboard/user_detail.html', {
        'target_user': target_user,
        'reports': reports,
        'claims': claims,
        'rewards': rewards,
        'alerts': alerts,
        'audit_history': audit_history,
        'role_form': role_form,
    })


@admin_only_required
def user_toggle_status_view(request, user_id):
    """Activates or deactivates an account with protection against self-lockout."""
    target_user = get_object_or_404(User, pk=user_id)

    if target_user == request.user:
        messages.error(request, "Security Safeguard: You cannot deactivate your own account.")
        return redirect('security_dashboard:user_detail', user_id=target_user.pk)

    new_status = not target_user.is_active
    target_user.is_active = new_status
    target_user.save(update_fields=['is_active'])

    action_label = "activated" if new_status else "deactivated"
    AuditService.log_action(
        action='user_status',
        actor=request.user,
        target_obj=target_user,
        details={'is_active': new_status, 'note': f"Account {action_label} by administrator."},
        request=request
    )

    messages.success(request, f"User account for '{target_user.username}' has been {action_label}.")
    return redirect('security_dashboard:user_detail', user_id=target_user.pk)


@admin_only_required
def user_update_role_view(request, user_id):
    """Updates user role with strict privilege escalation barriers."""
    target_user = get_object_or_404(User, pk=user_id)

    if target_user == request.user and not request.user.is_superuser:
        messages.error(request, "Security Safeguard: You cannot modify your own administrative role.")
        return redirect('security_dashboard:user_detail', user_id=target_user.pk)

    if request.method == 'POST':
        form = UserRoleUpdateForm(request.POST, instance=target_user, actor=request.user)
        if form.is_valid():
            old_role = target_user.role
            new_role = form.cleaned_data['role']
            form.save()

            AuditService.log_action(
                action='user_role',
                actor=request.user,
                target_obj=target_user,
                details={'old_role': old_role, 'new_role': new_role},
                request=request
            )
            messages.success(request, f"Role for '{target_user.username}' changed to '{target_user.get_role_display()}'.")
        else:
            messages.error(request, "Invalid role update requested.")

    return redirect('security_dashboard:user_detail', user_id=target_user.pk)


# --------------------------------------------------------------------------
# 3. ITEM GOVERNANCE, ARCHIVING, CATEGORIES & LOCATIONS
# --------------------------------------------------------------------------

@staff_or_admin_required
def item_management_list_view(request):
    """Item reports management with filtering for expired, unclaimed, and archived listings."""
    items_qs = Item.objects.all().select_related('category', 'location', 'user', 'institution').order_by('-created_at')
    if not request.user.is_superuser and request.user.institution:
        items_qs = items_qs.filter(institution=request.user.institution)

    # Search query
    q = request.GET.get('q', '').strip()
    if q:
        items_qs = items_qs.filter(
            Q(title__icontains=q) |
            Q(item_code__icontains=q) |
            Q(description__icontains=q) |
            Q(user__username__icontains=q)
        )

    # Filters
    report_type = request.GET.get('type', '')
    if report_type in ['lost', 'found']:
        items_qs = items_qs.filter(report_type=report_type)

    status_filter = request.GET.get('status', '')
    if status_filter:
        items_qs = items_qs.filter(status=status_filter)

    category_id = request.GET.get('category', '')
    if category_id:
        items_qs = items_qs.filter(category_id=category_id)

    location_id = request.GET.get('location', '')
    if location_id:
        items_qs = items_qs.filter(location_id=location_id)

    paginator = Paginator(items_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    categories = Category.objects.filter(is_active=True)
    locations = CampusLocation.objects.filter(is_active=True)

    return render(request, 'dashboard/items.html', {
        'page_obj': page_obj,
        'q': q,
        'report_type': report_type,
        'status_filter': status_filter,
        'category_id': category_id,
        'location_id': location_id,
        'categories': categories,
        'locations': locations,
        'statuses': Item.STATUS_CHOICES,
    })


@staff_or_admin_required
def item_archive_view(request, item_id):
    """Archives an old report without losing history or associated records."""
    item = get_object_or_404(Item, pk=item_id)

    old_status = item.status
    item.status = Item.STATUS_ARCHIVED
    item.save(update_fields=['status', 'updated_at'])

    ItemStatusHistory.objects.create(
        item=item,
        changed_by=request.user,
        old_status=old_status,
        new_status=Item.STATUS_ARCHIVED,
        remarks=f"Archived by campus administrator ({request.user.display_name})."
    )

    AuditService.log_action(
        action='item_archive',
        actor=request.user,
        target_obj=item,
        details={'old_status': old_status, 'new_status': Item.STATUS_ARCHIVED},
        request=request
    )

    messages.info(request, f"Item report '{item.title}' has been archived.")
    return redirect('security_dashboard:items')


@staff_or_admin_required
def category_management_view(request):
    """Manages categories and icons."""
    categories = Category.objects.annotate(items_count=Count('items')).order_by('name')

    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            cat = form.save(commit=False)
            if request.user.institution:
                cat.institution = request.user.institution
            cat.save()

            AuditService.log_action(
                action='category_modify',
                actor=request.user,
                target_obj=cat,
                details={'action': 'created', 'name': cat.name},
                request=request
            )
            messages.success(request, f"Category '{cat.name}' created.")
            return redirect('security_dashboard:categories')
    else:
        form = CategoryForm()

    return render(request, 'dashboard/categories.html', {
        'categories': categories,
        'form': form,
    })


@staff_or_admin_required
def location_management_view(request):
    """Manages campus locations and GPS coordinates for heatmap plotting."""
    locations = CampusLocation.objects.annotate(items_count=Count('items')).order_by('building', 'name')

    if request.method == 'POST':
        form = CampusLocationForm(request.POST)
        if form.is_valid():
            loc = form.save(commit=False)
            if request.user.institution:
                loc.institution = request.user.institution
            loc.save()

            AuditService.log_action(
                action='location_modify',
                actor=request.user,
                target_obj=loc,
                details={'action': 'created', 'name': loc.name, 'lat': loc.latitude, 'lng': loc.longitude},
                request=request
            )
            messages.success(request, f"Campus location '{loc.name}' configured with coordinates.")
            return redirect('security_dashboard:locations')
    else:
        form = CampusLocationForm()

    return render(request, 'dashboard/locations.html', {
        'locations': locations,
        'form': form,
    })


# --------------------------------------------------------------------------
# 4. CLAIM MODERATION
# --------------------------------------------------------------------------

@staff_or_admin_required
def claims_moderation_list_view(request):
    """Review queue for ownership claims with risk indicators."""
    claims_qs = Claim.objects.all().select_related('item', 'claimant', 'reviewed_by').order_by('-created_at')
    if not request.user.is_superuser and request.user.institution:
        claims_qs = claims_qs.filter(item__institution=request.user.institution)

    status_filter = request.GET.get('status', '')
    if status_filter:
        claims_qs = claims_qs.filter(status=status_filter)

    risk_filter = request.GET.get('risk', '')
    if risk_filter == 'high':
        claims_qs = claims_qs.filter(fraud_risk_score__gte=50)

    paginator = Paginator(claims_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'dashboard/claims.html', {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'risk_filter': risk_filter,
        'statuses': Claim.STATUS_CHOICES,
    })


@staff_or_admin_required
def claim_moderation_decision_view(request, claim_id):
    """
    Moderation view for an ownership claim.
    Presents private verification answers, proof image, and competing claims.
    Enforces that conflicting claims cannot be approved.
    """
    claim = get_object_or_404(
        Claim.objects.select_related('item', 'claimant', 'reviewed_by'),
        pk=claim_id
    )

    # Detect competing claims on the same item
    competing_claims = (
        Claim.objects.filter(item=claim.item)
        .exclude(pk=claim.pk)
        .select_related('claimant')
    )
    already_approved = competing_claims.filter(status=Claim.STATUS_APPROVED).first()

    if request.method == 'POST':
        action = request.POST.get('action')
        decision_reason = request.POST.get('decision_reason', '').strip()

        if not decision_reason:
            messages.error(request, "A clear decision explanation is mandatory.")
            return redirect('security_dashboard:claim_detail', claim_id=claim.pk)

        if action == 'approve':
            if already_approved:
                messages.error(
                    request,
                    f"Conflict Blocked: Claim #{already_approved.pk} is already approved for this item. "
                    "Reject or revoke that claim before approving another."
                )
                return redirect('security_dashboard:claim_detail', claim_id=claim.pk)

            old_status = claim.status
            claim.status = Claim.STATUS_APPROVED
            claim.decision_reason = decision_reason
            claim.reviewed_by = request.user
            claim.reviewed_at = timezone.now()
            claim.save()

            claim.item.status = Item.STATUS_CLAIMED
            claim.item.save(update_fields=['status', 'updated_at'])

            NotificationService.notify_claim_status_changed(claim, old_status, Claim.STATUS_APPROVED, decision_reason)

            AuditService.log_action(
                action='claim_decision',
                actor=request.user,
                target_obj=claim,
                details={'decision': 'approved', 'reason': decision_reason},
                request=request
            )
            messages.success(request, f"Claim #{claim.pk} approved. Ownership verified.")

        elif action == 'reject':
            old_status = claim.status
            claim.status = Claim.STATUS_REJECTED
            claim.decision_reason = decision_reason
            claim.reviewed_by = request.user
            claim.reviewed_at = timezone.now()
            claim.save()

            NotificationService.notify_claim_status_changed(claim, old_status, Claim.STATUS_REJECTED, decision_reason)

            AuditService.log_action(
                action='claim_decision',
                actor=request.user,
                target_obj=claim,
                details={'decision': 'rejected', 'reason': decision_reason},
                request=request
            )
            messages.warning(request, f"Claim #{claim.pk} rejected.")

        return redirect('security_dashboard:claims')

    return render(request, 'dashboard/claim_decision.html', {
        'claim': claim,
        'competing_claims': competing_claims,
        'already_approved': already_approved,
    })


# --------------------------------------------------------------------------
# 5. SECURITY MONITORING & ALERTS
# --------------------------------------------------------------------------

@staff_or_admin_required
def security_alerts_view(request):
    """Unified security monitoring view with explainable risk flags."""
    institution = request.user.institution
    SecurityMonitoringService.sync_security_alerts(institution)

    alerts_qs = SecurityAlert.objects.all().select_related('user', 'item', 'claim', 'handover', 'reviewed_by').order_by('-created_at')

    type_filter = request.GET.get('type', '')
    if type_filter:
        alerts_qs = alerts_qs.filter(alert_type=type_filter)

    severity_filter = request.GET.get('severity', '')
    if severity_filter:
        alerts_qs = alerts_qs.filter(severity=severity_filter)

    status_filter = request.GET.get('status', '')
    if status_filter:
        alerts_qs = alerts_qs.filter(status=status_filter)

    paginator = Paginator(alerts_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    summary = SecurityMonitoringService.get_alerts_summary(institution)

    return render(request, 'dashboard/security_alerts.html', {
        'page_obj': page_obj,
        'summary': summary,
        'type_filter': type_filter,
        'severity_filter': severity_filter,
        'status_filter': status_filter,
        'alert_types': SecurityAlert.ALERT_TYPE_CHOICES,
        'severities': SecurityAlert.SEVERITY_CHOICES,
        'statuses': SecurityAlert.STATUS_CHOICES,
    })


@staff_or_admin_required
def security_alert_action_view(request, alert_id):
    """Processes review decision on a security alert without automated banning."""
    alert = get_object_or_404(SecurityAlert, pk=alert_id)

    if request.method == 'POST':
        form = SecurityAlertReviewForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            notes = form.cleaned_data['review_notes']

            SecurityMonitoringService.review_alert(
                alert=alert,
                staff_user=request.user,
                new_status=new_status,
                review_notes=notes,
                request=request
            )
            messages.success(request, f"Security alert #{alert.pk} status updated to '{alert.get_status_display()}'.")
        else:
            messages.error(request, "Invalid alert review form.")

    return redirect('security_dashboard:security_alerts')


# --------------------------------------------------------------------------
# 6. AUDIT LOGS
# --------------------------------------------------------------------------

@staff_or_admin_required
def audit_logs_view(request):
    """Tamper-resistant audit log browser."""
    logs_qs = AuditLog.objects.all().select_related('actor', 'institution').order_by('-timestamp')
    if not request.user.is_superuser and request.user.institution:
        logs_qs = logs_qs.filter(institution=request.user.institution)

    action_filter = request.GET.get('action', '')
    if action_filter:
        logs_qs = logs_qs.filter(action=action_filter)

    actor_q = request.GET.get('actor', '').strip()
    if actor_q:
        logs_qs = logs_qs.filter(actor__username__icontains=actor_q)

    model_filter = request.GET.get('model', '').strip()
    if model_filter:
        logs_qs = logs_qs.filter(target_model__icontains=model_filter)

    paginator = Paginator(logs_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'dashboard/audit_logs.html', {
        'page_obj': page_obj,
        'action_filter': action_filter,
        'actor_q': actor_q,
        'model_filter': model_filter,
        'actions': AuditLog.ACTION_CHOICES,
    })


# --------------------------------------------------------------------------
# 7. ANALYTICS & INTELLIGENCE
# --------------------------------------------------------------------------

@staff_or_admin_required
def analytics_view(request):
    """Detailed analytics, charts, recovery trends, and location hot-spots."""
    institution = request.user.institution

    kpis = AnalyticsService.get_kpis(institution)
    monthly_trends = AnalyticsService.get_monthly_trends(institution, months_count=12)
    yearly_trends = AnalyticsService.get_yearly_trends(institution, years_count=3)
    category_stats = AnalyticsService.get_category_stats(institution)
    location_stats = AnalyticsService.get_location_stats(institution, limit=10)
    moderation_stats = AnalyticsService.get_claim_moderation_stats(institution)

    return render(request, 'dashboard/analytics.html', {
        'kpis': kpis,
        'monthly_trends': monthly_trends,
        'yearly_trends': yearly_trends,
        'category_stats': category_stats,
        'location_stats': location_stats,
        'moderation_stats': moderation_stats,
    })


# --------------------------------------------------------------------------
# 7B. LOST-ITEM TREND PREDICTIONS & HEURISTICS
# --------------------------------------------------------------------------

@staff_or_admin_required
def trend_predictions_view(request):
    """Predictive trend modeling, category vulnerability rankings, and patrol scheduling."""
    institution = request.user.institution
    days = int(request.GET.get('days', 90))
    predictions = PredictionService.get_predictions(institution=institution, days_lookback=days)

    return render(request, 'dashboard/predictions.html', {
        'predictions': predictions,
        'days': days,
    })


# --------------------------------------------------------------------------
# 8. CAMPUS HEATMAP
# --------------------------------------------------------------------------

@staff_or_admin_required
def campus_heatmap_view(request):
    """Geographic heatmap visualizing report clusters on approved campus coordinates."""
    institution = request.user.institution

    report_type = request.GET.get('type', 'all')
    category_id = request.GET.get('category', None)
    days = int(request.GET.get('days', 30))

    heatmap_data = HeatmapService.get_heatmap_data(
        institution=institution,
        report_type=report_type,
        category_id=category_id,
        days=days
    )

    categories = Category.objects.filter(is_active=True)

    return render(request, 'dashboard/heatmap.html', {
        'heatmap_data': heatmap_data,
        'report_type': report_type,
        'category_id': category_id,
        'days': days,
        'categories': categories,
    })


# --------------------------------------------------------------------------
# 9. REPORT EXPORTS (EXCEL & PDF)
# --------------------------------------------------------------------------

@staff_or_admin_required
def export_reports_view(request):
    """Generates downloadable Excel (.xlsx) and PDF (.pdf) activity summaries."""
    if request.method == 'POST':
        form = ReportExportFilterForm(request.POST)
        if form.is_valid():
            export_format = form.cleaned_data['export_format']
            report_type = form.cleaned_data.get('report_type')
            status = form.cleaned_data.get('status')
            category = form.cleaned_data.get('category')
            location = form.cleaned_data.get('location')
            date_from = form.cleaned_data.get('date_from')
            date_to = form.cleaned_data.get('date_to')

            # Filter items
            items_qs = Item.objects.all()
            filters_summary = []

            if report_type and report_type != 'all':
                items_qs = items_qs.filter(report_type=report_type)
                filters_summary.append(f"Type: {report_type.upper()}")

            if status and status != 'all':
                items_qs = items_qs.filter(status=status)
                filters_summary.append(f"Status: {status}")

            if category:
                items_qs = items_qs.filter(category=category)
                filters_summary.append(f"Category: {category.name}")

            if location:
                items_qs = items_qs.filter(location=location)
                filters_summary.append(f"Location: {location.name}")

            if date_from:
                items_qs = items_qs.filter(date_lost_or_found__gte=date_from)
                filters_summary.append(f"From: {date_from}")

            if date_to:
                items_qs = items_qs.filter(date_lost_or_found__lte=date_to)
                filters_summary.append(f"To: {date_to}")

            filter_str = ", ".join(filters_summary) if filters_summary else "All Records"

            # Log export to audit log
            AuditService.log_action(
                action='export_data',
                actor=request.user,
                details={'format': export_format, 'filters': filter_str, 'count': items_qs.count()},
                request=request
            )

            timestamp = timezone.now().strftime('%Y%m%d_%H%M')

            if export_format == 'xlsx':
                excel_buffer = ReportExportService.export_items_excel(items_qs, filters_summary=filter_str)
                response = HttpResponse(
                    excel_buffer.getvalue(),
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                response['Content-Disposition'] = f'attachment; filename="CampusCare_Report_{timestamp}.xlsx"'
                return response
            else:
                pdf_buffer = ReportExportService.export_items_pdf(items_qs, filters_summary=filter_str)
                response = HttpResponse(
                    pdf_buffer.getvalue(),
                    content_type='application/pdf'
                )
                response['Content-Disposition'] = f'attachment; filename="CampusCare_Report_{timestamp}.pdf"'
                return response
    else:
        form = ReportExportFilterForm()

    return render(request, 'dashboard/exports.html', {
        'form': form,
    })

