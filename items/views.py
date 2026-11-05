import csv
import datetime
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from core.models import CampusLocation, Category, Institution
from .forms import (
    AnonymousMessageForm,
    ClaimReviewForm,
    ClaimSubmissionForm,
    DismissMatchForm,
    HandoverInitiateForm,
    ItemReportForm,
    ItemStatusUpdateForm,
    NotificationPreferenceForm,
    OTPVerificationForm,
    ReportAbuseForm,
)
from .models import (
    Badge,
    Claim,
    ClaimStatusHistory,
    ConversationMessage,
    Handover,
    Item,
    ItemConversation,
    ItemMatch,
    ItemStatusHistory,
    Notification,
    NotificationPreference,
    RecoveryReceipt,
    RewardRule,
    RewardTransaction,
    UserBadge,
)
from .services import (
    CommunicationService,
    FraudDetector,
    MatchingService,
    NotificationService,
    TagService,
    QRService,
    RewardService,
)


def home_view(request):
    """
    CampusCare Root URL Handler.
    Authentication-first architecture:
    - If unauthenticated, redirect directly to the Login page.
    - If authenticated, redirect directly to the personal dashboard.
    """
    if not request.user.is_authenticated:
        return redirect('login')
    return redirect('dashboard')


@login_required
def dashboard_view(request):
    """
    Personal student / faculty / staff dashboard.
    Shows real database metrics:
    - Total Lost items reported
    - Total Found items reported
    - Active Reports
    - Recovered Items
    - Pending Claims
    - Reward Points
    Plus:
    - Suggested matching items (using MatchingService)
    - Recent campus reports
    - Recent notifications
    - Interactive report filtering & search
    """
    user = request.user
    institution = getattr(user, 'institution', None)
    if institution:
        campus_items = Item.objects.filter(institution=institution)
    else:
        campus_items = Item.objects.all()

    # CSV Export Handler
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        filename = f"campuscare_reports_{timezone.now().strftime('%Y%m%d_%H%M')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Title', 'Type', 'Category', 'Location', 'Status', 'Date Reported'])
        for itm in campus_items.select_related('category', 'location').order_by('-created_at')[:300]:
            writer.writerow([
                itm.pk,
                itm.title,
                itm.get_report_type_display(),
                itm.category.name if itm.category else 'General',
                itm.location.name if itm.location else 'Campus',
                itm.get_status_display(),
                itm.created_at.strftime('%Y-%m-%d %H:%M')
            ])
        return response

    user_items = Item.objects.filter(user=user).select_related('category', 'location')
    user_claims = Claim.objects.filter(claimant=user).select_related('item', 'item__category', 'item__location')

    # Tab and search filtering on user's reports
    tab = request.GET.get('tab', 'all')
    q = request.GET.get('q', '').strip()
    filtered_items = user_items

    if q:
        filtered_items = filtered_items.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(category__name__icontains=q)
        )

    if tab == 'lost':
        filtered_items = filtered_items.filter(report_type=Item.REPORT_TYPE_LOST)
    elif tab == 'found':
        filtered_items = filtered_items.filter(report_type=Item.REPORT_TYPE_FOUND)
    elif tab == 'resolved':
        filtered_items = filtered_items.filter(status__in=[Item.STATUS_CLAIMED, Item.STATUS_RETURNED])
    elif tab == 'open':
        filtered_items = filtered_items.filter(status=Item.STATUS_OPEN)
    elif tab == 'claims':
        filtered_items = None

    page_obj = None
    if filtered_items is not None:
        paginator = Paginator(filtered_items.order_by('-created_at'), 8)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

    # Real DB-derived dashboard statistics
    stats = {
        'total_lost': campus_items.filter(report_type=Item.REPORT_TYPE_LOST).count(),
        'total_found': campus_items.filter(report_type=Item.REPORT_TYPE_FOUND).count(),
        'active_reports': user_items.filter(status=Item.STATUS_OPEN).count(),
        'recovered_items': campus_items.filter(status=Item.STATUS_RETURNED).count(),
        'pending_claims': user_claims.filter(status__in=[Claim.STATUS_PENDING, Claim.STATUS_UNDER_REVIEW]).count(),
        'reward_points': user.reward_points,
        # Tab counts
        'total': user_items.count(),
        'lost': user_items.filter(report_type=Item.REPORT_TYPE_LOST).count(),
        'found': user_items.filter(report_type=Item.REPORT_TYPE_FOUND).count(),
        'resolved': user_items.filter(status__in=[Item.STATUS_CLAIMED, Item.STATUS_RETURNED]).count(),
        'open': user_items.filter(status=Item.STATUS_OPEN).count(),
        'claims_count': user_claims.count(),
    }

    # Analytics: Recovery Activity monthly trend for past 6 months
    now = timezone.now()
    recovery_trend = []
    for i in range(5, -1, -1):
        m_year = now.year
        m_month = now.month - i
        while m_month <= 0:
            m_month += 12
            m_year -= 1
        m_date = datetime.date(m_year, m_month, 1)
        month_label = m_date.strftime('%b')
        rep_count = campus_items.filter(created_at__year=m_year, created_at__month=m_month).count()
        rec_count = campus_items.filter(status=Item.STATUS_RETURNED, updated_at__year=m_year, updated_at__month=m_month).count()
        recovery_trend.append({
            'month': month_label,
            'reported': rep_count,
            'recovered': rec_count,
        })

    # Analytics: Report Status Breakdown
    status_breakdown = {
        'open': campus_items.filter(status=Item.STATUS_OPEN).count(),
        'under_claim': campus_items.filter(status__in=[Item.STATUS_PENDING, Item.STATUS_CLAIMED]).count(),
        'recovered': campus_items.filter(status=Item.STATUS_RETURNED).count(),
        'expired': campus_items.filter(status__in=[Item.STATUS_EXPIRED, Item.STATUS_CLOSED]).count(),
    }

    # Institutions for campus selector
    institutions = Institution.objects.filter(is_active=True).order_by('name')

    # Suggested smart matches for user's open items
    suggested_matches = []
    open_items = user_items.filter(status=Item.STATUS_OPEN)[:5]
    for itm in open_items:
        matches = MatchingService.find_matches_for_item(itm, min_score=40, limit=3)
        suggested_matches.extend(matches)
    # Deduplicate matches
    seen_ids = set()
    unique_matches = []
    for m in suggested_matches:
        if m.pk not in seen_ids:
            seen_ids.add(m.pk)
            unique_matches.append(m)
    unique_matches.sort(key=lambda m: m.score, reverse=True)

    # Recent notifications
    recent_notifications = Notification.objects.filter(
        recipient=user
    ).order_by('-created_at')[:6]

    # Recent items reported on campus
    recent_campus_items = campus_items.select_related(
        'category', 'location', 'user'
    ).order_by('-created_at')[:8]

    return render(request, 'items/dashboard.html', {
        'is_dashboard': True,
        'page_obj': page_obj,
        'current_tab': tab,
        'search_query': q,
        'stats': stats,
        'recovery_trend': recovery_trend,
        'status_breakdown': status_breakdown,
        'chart_labels': json.dumps([x['month'] for x in recovery_trend]),
        'chart_reported': json.dumps([x['reported'] for x in recovery_trend]),
        'chart_recovered': json.dumps([x['recovered'] for x in recovery_trend]),
        'chart_status_data': json.dumps([
            status_breakdown['open'],
            status_breakdown['under_claim'],
            status_breakdown['recovered'],
            status_breakdown['expired'],
        ]),
        'institutions': institutions,
        'user_claims': user_claims.order_by('-created_at')[:10],
        'suggested_matches': unique_matches[:6],
        'recent_notifications': recent_notifications,
        'recent_campus_items': recent_campus_items,
    })


@login_required
def my_reports_view(request):
    """
    Dedicated My Reports view for the authenticated user.
    Displays only items reported by the currently logged-in user with
    dedicated KPI statistics, search, filters, pagination, and item actions.
    Never shows the entire campus dashboard.
    """
    user = request.user
    user_reports = Item.objects.filter(
        user=user
    ).select_related('category', 'location', 'institution').prefetch_related('claims')

    # Calculate dedicated user report KPI metrics
    stats = {
        'total_reports': user_reports.count(),
        'active_reports': user_reports.filter(status=Item.STATUS_OPEN).count(),
        'pending_claims': Claim.objects.filter(
            item__user=user,
            status__in=[Claim.STATUS_PENDING, Claim.STATUS_UNDER_REVIEW]
        ).count(),
        'recovered_items': user_reports.filter(status=Item.STATUS_RETURNED).count(),
    }

    # Filters and search query
    q = request.GET.get('q', '').strip()
    report_type = request.GET.get('type', '').strip()
    status = request.GET.get('status', '').strip()
    sort = request.GET.get('sort', '-created_at').strip()

    filtered_reports = user_reports

    if q:
        filtered_reports = filtered_reports.filter(
            Q(title__icontains=q) |
            Q(item_code__icontains=q) |
            Q(description__icontains=q) |
            Q(category__name__icontains=q) |
            Q(location__name__icontains=q)
        )

    if report_type in [Item.REPORT_TYPE_LOST, Item.REPORT_TYPE_FOUND]:
        filtered_reports = filtered_reports.filter(report_type=report_type)

    if status and status in dict(Item.STATUS_CHOICES):
        filtered_reports = filtered_reports.filter(status=status)

    valid_sorts = {
        '-created_at': '-created_at',
        'created_at': 'created_at',
        '-date_lost_or_found': '-date_lost_or_found',
        'date_lost_or_found': 'date_lost_or_found',
    }
    filtered_reports = filtered_reports.order_by(valid_sorts.get(sort, '-created_at'))

    paginator = Paginator(filtered_reports, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'items/my_reports.html', {
        'reports': page_obj,
        'page_obj': page_obj,
        'stats': stats,
        'q': q,
        'selected_type': report_type,
        'selected_status': status,
        'selected_sort': sort,
        'status_choices': Item.STATUS_CHOICES,
    })


@login_required
def recovery_history_view(request):
    """
    List recovery records and confirmed handovers for the authenticated student or staff.
    Properly scopes queryset using actual model relationships: handovers where user is
    claimant, holder, or item reporter. Provides filtering, searching, sorting,
    KPI summary metrics from database, and CSV export.
    """
    user = request.user

    # Multi-tenant scoping and student-privacy authorization:
    # A student can ONLY see handovers where they are the verified claimant,
    # the custodian/holder, or the original reporter of the item.
    if user.is_staff_member:
        institution = getattr(request, 'institution', None) or getattr(user, 'institution', None)
        if institution:
            base_qs = Handover.objects.filter(
                Q(item__institution=institution) | Q(item__institution__isnull=True)
            )
        else:
            base_qs = Handover.objects.all()
    else:
        base_qs = Handover.objects.filter(
            Q(claimant=user) | Q(held_by=user) | Q(item__user=user)
        )

    # Summary Cards: All values calculated from actual database records
    total_handovers = base_qs.count()
    total_recovered = base_qs.filter(status=Handover.STATUS_VERIFIED).count()

    total_reward_points = RewardTransaction.objects.filter(
        user=user
    ).aggregate(total=Sum('points'))['total']
    if total_reward_points is None:
        total_reward_points = getattr(user, 'reward_points', 0)

    # Prepare queryset with related models for efficient display without N+1 queries
    queryset = base_qs.select_related(
        'item',
        'item__category',
        'item__location',
        'item__user',
        'claim',
        'claimant',
        'held_by',
        'receipt'
    ).prefetch_related(
        'reward_transactions'
    ).distinct()

    # Search filter (by item name, reference code, receipt number, location, or notes)
    q = request.GET.get('q', '').strip()
    if q:
        queryset = queryset.filter(
            Q(item__title__icontains=q) |
            Q(item__item_code__icontains=q) |
            Q(receipt__receipt_number__icontains=q) |
            Q(handover_location__icontains=q) |
            Q(item__location__name__icontains=q)
        )

    # Category filter
    category_id = request.GET.get('category', '').strip()
    if category_id:
        queryset = queryset.filter(item__category_id=category_id)

    # Status filter
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    # Recovery date filter
    date_filter = request.GET.get('date', '').strip()
    if date_filter:
        now = timezone.now()
        if date_filter == 'today':
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            queryset = queryset.filter(
                Q(verified_at__gte=today_start) | (Q(verified_at__isnull=True) & Q(initiated_at__gte=today_start))
            )
        elif date_filter == 'week':
            week_ago = now - datetime.timedelta(days=7)
            queryset = queryset.filter(
                Q(verified_at__gte=week_ago) | (Q(verified_at__isnull=True) & Q(initiated_at__gte=week_ago))
            )
        elif date_filter == 'month':
            month_ago = now - datetime.timedelta(days=30)
            queryset = queryset.filter(
                Q(verified_at__gte=month_ago) | (Q(verified_at__isnull=True) & Q(initiated_at__gte=month_ago))
            )
        elif date_filter == 'year':
            year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            queryset = queryset.filter(
                Q(verified_at__gte=year_start) | (Q(verified_at__isnull=True) & Q(initiated_at__gte=year_start))
            )

    # Sorting
    sort_by = request.GET.get('sort', 'newest').strip()
    if sort_by == 'oldest':
        queryset = queryset.order_by(F('verified_at').asc(nulls_last=True), 'initiated_at')
    elif sort_by == 'title':
        queryset = queryset.order_by('item__title')
    else:  # newest by default
        queryset = queryset.order_by(F('verified_at').desc(nulls_last=True), '-initiated_at')

    # Optional Real CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="campuscare_recovery_history.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Item Title',
            'Reference Code',
            'Category',
            'Report Type',
            'Reported Date',
            'Recovery Date',
            'Location',
            'Status',
            'Receipt Number',
            'Claim ID',
            'User Role',
        ])
        for h in queryset:
            receipt_num = h.receipt.receipt_number if getattr(h, 'receipt', None) else 'N/A'
            recovery_dt = h.verified_at.strftime('%Y-%m-%d %H:%M') if h.verified_at else (h.initiated_at.strftime('%Y-%m-%d %H:%M') if h.initiated_at else 'N/A')
            reported_dt = h.item.date_lost_or_found.strftime('%Y-%m-%d') if h.item and h.item.date_lost_or_found else 'N/A'
            if h.claimant == user:
                role = "Verified Owner"
            elif h.held_by == user:
                role = "Custodian / Finder"
            else:
                role = "Item Reporter"

            writer.writerow([
                h.item.title if h.item else 'N/A',
                h.item.item_code if h.item else 'N/A',
                h.item.category.name if h.item and h.item.category else 'N/A',
                h.item.get_report_type_display() if h.item else 'N/A',
                reported_dt,
                recovery_dt,
                h.handover_location,
                h.get_status_display(),
                receipt_num,
                f"#{h.claim_id}" if h.claim_id else 'N/A',
                role,
            ])
        return response

    # Pagination
    paginator = Paginator(queryset, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.all().order_by('name')

    return render(request, 'items/recovery_history.html', {
        'page_obj': page_obj,
        'total_recovered': total_recovered,
        'total_handovers': total_handovers,
        'total_reward_points': total_reward_points,
        'categories': categories,
        'current_q': q,
        'current_category': category_id,
        'current_status': status_filter,
        'current_date': date_filter,
        'current_sort': sort_by,
        'STATUS_CHOICES': Handover.STATUS_CHOICES,
    })


def _filter_and_paginate_items(request, report_type):
    """Helper for filtering and paginating lost or found items with tenant isolation and federated search."""
    queryset = Item.objects.filter(report_type=report_type).select_related('category', 'location', 'user', 'institution')

    # Multi-tenant and Cross-Campus Scoping
    institution = getattr(request, 'institution', None)
    inst_id = request.GET.get('institution')
    cross_campus = request.GET.get('cross_campus')

    if inst_id:
        queryset = queryset.filter(institution_id=inst_id)
    elif cross_campus in ['1', 'true', 'all']:
        if institution:
            queryset = queryset.filter(Q(institution=institution) | Q(is_cross_campus_visible=True))
    else:
        if institution:
            queryset = queryset.filter(institution=institution)

    q = request.GET.get('q', '').strip()
    if q:
        queryset = queryset.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(location_details__icontains=q)
        )

    category_id = request.GET.get('category')
    if category_id:
        queryset = queryset.filter(category_id=category_id)

    location_id = request.GET.get('location')
    if location_id:
        queryset = queryset.filter(location_id=location_id)

    status = request.GET.get('status')
    if status:
        queryset = queryset.filter(status=status)
    else:
        status_view = request.GET.get('view_all')
        if not status_view:
            queryset = queryset.filter(status=Item.STATUS_OPEN)

    date_from = request.GET.get('date_from')
    if date_from:
        queryset = queryset.filter(date_lost_or_found__gte=date_from)
    date_to = request.GET.get('date_to')
    if date_to:
        queryset = queryset.filter(date_lost_or_found__lte=date_to)

    sort = request.GET.get('sort', '-created_at')
    valid_sorts = ['-created_at', 'created_at', '-date_lost_or_found', 'date_lost_or_found', 'title']
    if sort in valid_sorts:
        queryset = queryset.order_by(sort)

    paginator = Paginator(queryset, 12)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return page_obj, {
        'q': q,
        'category_id': category_id,
        'location_id': location_id,
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
        'sort': sort,
        'institution_id': inst_id,
        'cross_campus': cross_campus,
    }


def lost_items_view(request):
    """List of reported lost items with search, filters, and pagination."""
    page_obj, filters = _filter_and_paginate_items(request, Item.REPORT_TYPE_LOST)
    categories = Category.objects.filter(is_active=True)
    locations = CampusLocation.objects.filter(is_active=True)

    return render(request, 'items/lost_items.html', {
        'page_obj': page_obj,
        'categories': categories,
        'locations': locations,
        'filters': filters,
        'status_choices': Item.STATUS_CHOICES,
    })


def found_items_view(request):
    """List of reported found items with search, filters, and pagination."""
    page_obj, filters = _filter_and_paginate_items(request, Item.REPORT_TYPE_FOUND)
    categories = Category.objects.filter(is_active=True)
    locations = CampusLocation.objects.filter(is_active=True)

    return render(request, 'items/found_items.html', {
        'page_obj': page_obj,
        'categories': categories,
        'locations': locations,
        'filters': filters,
        'status_choices': Item.STATUS_CHOICES,
    })


@login_required
def report_item_view(request, report_type):
    """
    Create a new Lost or Found item report.
    Validates file upload, date, category, and location.
    """
    if report_type not in [Item.REPORT_TYPE_LOST, Item.REPORT_TYPE_FOUND]:
        messages.error(request, "Invalid report type specified.")
        return redirect('home')

    if request.method == 'POST':
        form = ItemReportForm(
            request.POST,
            request.FILES,
            user=request.user,
            report_type=report_type
        )
        if form.is_valid():
            item = form.save(commit=False)
            item.user = request.user
            item.report_type = report_type

            if request.user.institution:
                item.institution = request.user.institution
            else:
                first_inst = Institution.objects.filter(is_active=True).first()
                if not first_inst:
                    messages.error(request, "No active campus institution configured.")
                    return redirect('home')
                item.institution = first_inst

            form.save(commit=True)

            # Trigger initial match discovery in background
            try:
                matches = MatchingService.find_matches_for_item(item, min_score=40.0, limit=5)
                if matches:
                    top_match = matches[0]
                    NotificationService.notify_match_found(item, top_match.matched_item, top_match.score)
            except Exception:
                pass

            type_label = "Lost" if report_type == Item.REPORT_TYPE_LOST else "Found"
            messages.success(
                request,
                f"Your {type_label} Item report has been posted successfully! "
                "Smart matching has been initiated."
            )
            return redirect('items:item_detail', pk=item.pk)
        else:
            messages.error(request, "Please check the form for errors.")
    else:
        form = ItemReportForm(user=request.user, report_type=report_type)

    return render(request, 'items/report_item.html', {
        'form': form,
        'report_type': report_type,
    })


def build_item_timeline(item):
    """
    Constructs an explainable recovery event timeline for the item.
    Tracks creation, match discovery, claim submission, review, handover, and recovery.
    """
    events = []

    # 1. Report Created
    events.append({
        'stage': 'Report Created',
        'icon': 'fa-file-lines',
        'title': f"{item.get_report_type_display()} item report logged",
        'description': f"Reported for location: {item.location.name if item.location else 'Campus'} on {item.date_lost_or_found}.",
        'timestamp': item.created_at,
        'completed': True,
    })

    # 2. Suggested Match Found
    top_match = item.source_matches.order_by('-score').first()
    if top_match:
        events.append({
            'stage': 'Match Suggested',
            'icon': 'fa-wand-magic-sparkles',
            'title': f"Potential match discovered ({top_match.score:.0f}% compatibility)",
            'description': f"Smart matching identified compatible report: '{top_match.matched_item.title}'.",
            'timestamp': top_match.created_at,
            'completed': True,
        })

    # 3. Ownership Claim Submitted
    first_claim = item.claims.order_by('created_at').first()
    approved_claim = item.claims.filter(status=Claim.STATUS_APPROVED).first()
    if first_claim:
        events.append({
            'stage': 'Claim Submitted',
            'icon': 'fa-id-card',
            'title': "Ownership verification claim lodged",
            'description': f"Claim submitted by {first_claim.claimant.display_name} with private ownership answers.",
            'timestamp': first_claim.created_at,
            'completed': True,
        })

    # 4. Claim Reviewed & Approved
    if approved_claim and approved_claim.reviewed_at:
        events.append({
            'stage': 'Claim Approved',
            'icon': 'fa-circle-check',
            'title': "Ownership verified by campus staff",
            'description': f"Verified by {approved_claim.reviewed_by.display_name if approved_claim.reviewed_by else 'Staff'}. Ready for recovery handover.",
            'timestamp': approved_claim.reviewed_at,
            'completed': True,
        })
    elif first_claim:
        events.append({
            'stage': 'Claim Under Review',
            'icon': 'fa-clock',
            'title': "Ownership claim under staff review",
            'description': "Campus administrators are verifying submitted proof and private questions.",
            'timestamp': first_claim.updated_at,
            'completed': False,
        })

    # 5. Handover Initiated
    handover = getattr(approved_claim, 'handover', None) if approved_claim else None
    if not handover:
        handover = Handover.objects.filter(item=item).first()

    if handover:
        events.append({
            'stage': 'Handover Initiated',
            'icon': 'fa-handshake-simple',
            'title': "Physical recovery exchange scheduled",
            'description': f"Location: {handover.handover_location}. Secure 6-digit OTP active.",
            'timestamp': handover.initiated_at,
            'completed': True,
        })

    # 6. Item Recovered / Handed Over
    if item.status == Item.STATUS_RETURNED or (handover and handover.status == Handover.STATUS_VERIFIED):
        receipt = getattr(handover, 'receipt', None) if handover else None
        events.append({
            'stage': 'Item Recovered',
            'icon': 'fa-shield-heart',
            'title': "Item successfully recovered by verified owner",
            'description': f"Cryptographic Recovery Receipt #{receipt.receipt_number if receipt else 'FINAL'} generated.",
            'timestamp': handover.verified_at if (handover and handover.verified_at) else item.updated_at,
            'completed': True,
            'receipt': receipt,
        })

    return events


def item_detail_by_code_view(request, item_code):
    """
    Canonical public lookup for an item by reference code (from item tag or direct search).
    Gracefully handles active, expired, or invalid item codes.
    """
    code_clean = (item_code or '').strip()
    item = Item.objects.select_related('category', 'location', 'user', 'institution').filter(item_code__iexact=code_clean).first()
    if not item:
        import re
        m = re.search(r'(\d+)$', code_clean)
        if m:
            item = Item.objects.select_related('category', 'location', 'user', 'institution').filter(pk=int(m.group(1))).first()

    if not item:
        return render(request, 'items/item_not_found.html', {
            'item_code': code_clean,
            'is_invalid': True,
        }, status=404)

    return redirect('items:item_detail', pk=item.pk)


def item_detail_view(request, pk):
    """
    Detailed view of a reported item.
    Enforces privacy rules so that private contact details are never exposed publicly.
    Handles deleted and expired items gracefully.
    """
    item = Item.objects.select_related('category', 'location', 'user', 'institution').filter(pk=pk).first()
    if not item:
        return render(request, 'items/item_not_found.html', {
            'item_code': f"Item #{pk}",
            'is_invalid': True,
        }, status=404)

    if getattr(item, 'is_deleted', False):
        return render(request, 'items/item_not_found.html', {
            'item': item,
            'item_code': item.item_code or f"CC-{item.created_at.year}-{item.pk:05d}",
            'is_deleted': True,
        }, status=200 if request.user.is_authenticated and (item.user == request.user or getattr(request.user, 'is_staff_member', False)) else 404)

    can_edit = item.can_edit(request.user)
    can_delete = item.can_delete(request.user)
    can_view_contact = item.can_view_contact(request.user)
    history_logs = item.history.all().select_related('changed_by')

    # Suggested matches count (excluding dismissed)
    matches_count = ItemMatch.objects.filter(
        source_item=item,
        status=ItemMatch.STATUS_SUGGESTED
    ).count()

    # Ownership claims count
    claims_count = item.claims.count()
    user_active_claim = None
    if request.user.is_authenticated:
        user_active_claim = item.claims.filter(
            claimant=request.user,
            status__in=[Claim.STATUS_PENDING, Claim.STATUS_UNDER_REVIEW, Claim.STATUS_APPROVED]
        ).first()

    # Handover and Recovery Receipt for authorized participants
    item_handover = None
    item_receipt = None
    if request.user.is_authenticated:
        item_handover = Handover.objects.filter(item=item).first()
        if item_handover:
            item_receipt = getattr(item_handover, 'receipt', None)

    # Timeline events
    timeline_events = build_item_timeline(item)

    status_form = None
    if can_edit:
        status_form = ItemStatusUpdateForm(
            is_staff=getattr(request.user, 'is_staff_member', False),
            current_status=item.status
        )

    # Chat eligibility flags
    has_claims = item.claims.exists()
    is_reporter = request.user.is_authenticated and (request.user == item.user)
    chat_awaiting_claims = is_reporter and not has_claims

    return render(request, 'items/item_detail.html', {
        'item': item,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'can_view_contact': can_view_contact,
        'history_logs': history_logs,
        'status_form': status_form,
        'matches_count': matches_count,
        'claims_count': claims_count,
        'user_active_claim': user_active_claim,
        'item_handover': item_handover,
        'item_receipt': item_receipt,
        'timeline_events': timeline_events,
        'has_claims': has_claims,
        'is_reporter': is_reporter,
        'chat_awaiting_claims': chat_awaiting_claims,
    })


@login_required
def item_edit_view(request, pk):
    """Edit own report or manage report as administrator."""
    item = get_object_or_404(Item, pk=pk)

    if not item.can_edit(request.user):
        raise PermissionDenied("You do not have permission to edit this report.")

    if request.method == 'POST':
        form = ItemReportForm(
            request.POST,
            request.FILES,
            instance=item,
            user=request.user,
            report_type=item.report_type
        )
        if form.is_valid():
            form.save()
            ItemStatusHistory.objects.create(
                item=item,
                changed_by=request.user,
                old_status=item.status,
                new_status=item.status,
                remarks="Item details updated by reporter / administrator."
            )
            messages.success(request, "Item details updated successfully.")
            return redirect('items:item_detail', pk=item.pk)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ItemReportForm(
            instance=item,
            user=request.user,
            report_type=item.report_type
        )

    return render(request, 'items/item_edit.html', {
        'form': form,
        'item': item,
    })


@login_required
def item_delete_view(request, pk):
    """Delete own report or as administrator."""
    item = get_object_or_404(Item, pk=pk)

    if not item.can_delete(request.user):
        raise PermissionDenied("You do not have permission to delete this report.")

    if request.method == 'POST':
        item_title = item.title
        item.delete()
        messages.success(request, f"Report '{item_title}' has been deleted successfully.")
        return redirect('dashboard')

    return render(request, 'items/item_confirm_delete.html', {'item': item})


@login_required
def item_update_status_view(request, pk):
    """Update status of an item (e.g. mark claimed, returned to owner)."""
    item = get_object_or_404(Item, pk=pk)

    if not item.can_edit(request.user):
        raise PermissionDenied("You do not have permission to update this report.")

    if request.method == 'POST':
        is_staff = getattr(request.user, 'is_staff_member', False)
        form = ItemStatusUpdateForm(
            request.POST,
            is_staff=is_staff,
            current_status=item.status
        )
        if form.is_valid():
            old_status = item.status
            new_status = form.cleaned_data['status']
            remarks = form.cleaned_data.get('remarks', '').strip()

            if old_status != new_status or remarks:
                item.status = new_status
                item.save(update_fields=['status', 'updated_at'])

                if new_status == Item.STATUS_RETURNED and old_status != Item.STATUS_RETURNED:
                    if item.report_type == Item.REPORT_TYPE_FOUND and item.user:
                        item.user.reward_points += 50
                        item.user.save(update_fields=['reward_points'])
                        messages.success(request, f"50 Reward Points awarded to {item.user.display_name} for helping resolve this item!")

                ItemStatusHistory.objects.create(
                    item=item,
                    changed_by=request.user,
                    old_status=old_status,
                    new_status=new_status,
                    remarks=remarks or f"Status changed to {item.get_status_display()}"
                )
                messages.success(request, f"Status updated to '{item.get_status_display()}'.")
            else:
                messages.info(request, "No status change was made.")

    return redirect('items:item_detail', pk=item.pk)


@login_required
def admin_manage_reports_view(request):
    """Campus administrator and staff moderation dashboard."""
    if not getattr(request.user, 'is_staff_member', False):
        raise PermissionDenied("Only campus staff and administrators can access this view.")

    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    q = request.GET.get('q', '').strip()

    items = Item.objects.all().select_related('category', 'location', 'user', 'institution')

    if status_filter:
        items = items.filter(status=status_filter)
    if type_filter:
        items = items.filter(report_type=type_filter)
    if q:
        items = items.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(user__username__icontains=q) |
            Q(user__student_id__icontains=q)
        )

    paginator = Paginator(items, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    stats = {
        'total': Item.objects.count(),
        'open': Item.objects.filter(status=Item.STATUS_OPEN).count(),
        'pending': Item.objects.filter(status=Item.STATUS_PENDING).count(),
        'returned': Item.objects.filter(status=Item.STATUS_RETURNED).count(),
        'expired': Item.objects.filter(status=Item.STATUS_EXPIRED).count(),
        'total_claims': Claim.objects.count(),
        'pending_claims': Claim.objects.filter(status=Claim.STATUS_PENDING).count(),
    }

    return render(request, 'items/admin_manage.html', {
        'page_obj': page_obj,
        'stats': stats,
        'status_choices': Item.STATUS_CHOICES,
        'current_status': status_filter,
        'current_type': type_filter,
        'q': q,
    })


# --------------------------------------------------------------------------
# STEP 2: SMART ITEM MATCHING VIEWS
# --------------------------------------------------------------------------

@login_required
def item_matches_view(request, pk):
    """
    Displays suggested matches for an item.
    Computes explainable weighted similarity breakdown (category, text, location, date, image).
    Allows authenticated users to review suggestions and dismiss incorrect ones.
    """
    item = get_object_or_404(Item, pk=pk)

    # Permission check: owner or staff/admin
    if not (item.user == request.user or getattr(request.user, 'is_staff_member', False)):
        raise PermissionDenied("You can only view suggested matches for your own reports or as campus staff.")

    # Re-evaluate matches
    MatchingService.find_matches_for_item(item, min_score=35.0, limit=12)

    matches = ItemMatch.objects.filter(
        source_item=item,
        status=ItemMatch.STATUS_SUGGESTED
    ).select_related('matched_item__category', 'matched_item__location', 'matched_item__user')

    dismiss_form = DismissMatchForm()

    return render(request, 'items/item_matches.html', {
        'item': item,
        'matches': matches,
        'dismiss_form': dismiss_form,
    })


@login_required
def item_dismiss_match_view(request, pk, match_pk):
    """Allows users to dismiss a false or inaccurate match suggestion."""
    item = get_object_or_404(Item, pk=pk)
    match_obj = get_object_or_404(ItemMatch, pk=match_pk, source_item=item)

    if not (item.user == request.user or getattr(request.user, 'is_staff_member', False)):
        raise PermissionDenied("Permission denied.")

    if request.method == 'POST':
        form = DismissMatchForm(request.POST)
        reason = ""
        if form.is_valid():
            reason = form.cleaned_data.get('dismissed_reason', '')

        match_obj.status = ItemMatch.STATUS_DISMISSED
        match_obj.dismissed_by = request.user
        match_obj.dismissed_reason = reason or "Dismissed by user"
        match_obj.save(update_fields=['status', 'dismissed_by', 'dismissed_reason', 'updated_at'])

        messages.info(request, "Suggestion dismissed. It will no longer appear in your matches.")

    return redirect('items:item_matches', pk=item.pk)


# --------------------------------------------------------------------------
# STEP 2: OWNERSHIP VERIFICATION & CLAIMS VIEWS
# --------------------------------------------------------------------------

@login_required
def item_claim_create_view(request, pk):
    """
    Submit an ownership claim for a found item.
    Enforces server-side validation, fraud risk scoring, and privacy protections.
    """
    item = get_object_or_404(Item, pk=pk)

    # Pre-validation checks
    if item.user == request.user:
        messages.error(request, "You cannot submit an ownership claim for an item you reported yourself.")
        return redirect('items:item_detail', pk=item.pk)

    if item.status in [Item.STATUS_RETURNED, Item.STATUS_CLOSED]:
        messages.error(request, "This item has already been resolved or closed. No new claims are accepted.")
        return redirect('items:item_detail', pk=item.pk)

    # Check for active existing claim by this user
    existing_claim = Claim.objects.filter(
        item=item,
        claimant=request.user,
        status__in=[Claim.STATUS_PENDING, Claim.STATUS_UNDER_REVIEW]
    ).first()
    if existing_claim:
        messages.warning(request, "You already have a pending claim under review for this item.")
        return redirect('items:claim_detail', pk=existing_claim.pk)

    if request.method == 'POST':
        form = ClaimSubmissionForm(
            request.POST,
            request.FILES,
            item=item,
            claimant=request.user
        )
        if form.is_valid():
            details = form.cleaned_data.get('identifying_details', '')

            # Calculate explainable fraud risk indicators
            risk_score, risk_flags = FraudDetector.analyze_claim_risk(
                request.user,
                item,
                details
            )

            try:
                claim = form.save_with_answers(commit=False)
                claim.fraud_risk_score = risk_score
                claim.fraud_risk_flags = risk_flags
                claim.save()

                # Dispatch notifications
                NotificationService.notify_claim_submitted(claim)

                messages.success(
                    request,
                    "Your ownership claim has been securely submitted! "
                    "Campus security and administrators will verify your answers. "
                    "Your private answers remain strictly confidential."
                )
                return redirect('items:claim_detail', pk=claim.pk)

            except ValidationError as e:
                form.add_error(None, e)
        else:
            messages.error(request, "Please check the form and provide complete verification details.")
    else:
        form = ClaimSubmissionForm(item=item, claimant=request.user)

    return render(request, 'items/claim_form.html', {
        'item': item,
        'form': form,
    })


@login_required
def claim_detail_view(request, pk):
    """
    Detailed view of a claim.
    PRIVACY ENFORCEMENT:
    - Only the claimant and campus staff/admin can view private verification answers.
    - Other students/claimants receive a 403 Forbidden.
    """
    claim = get_object_or_404(
        Claim.objects.select_related('item', 'claimant', 'reviewed_by'),
        pk=pk
    )

    is_claimant = (request.user == claim.claimant)
    is_staff = getattr(request.user, 'is_staff_member', False)

    # Access check
    if not (is_claimant or is_staff):
        raise PermissionDenied("You do not have permission to view this ownership claim.")

    can_view_private_answers = claim.can_view_private_answers(request.user)
    history_logs = claim.history.all().select_related('changed_by')

    # Competing claims count on the same item (staff only)
    competing_claims_count = 0
    if is_staff:
        competing_claims_count = Claim.objects.filter(item=claim.item).exclude(pk=claim.pk).count()

    return render(request, 'items/claim_detail.html', {
        'claim': claim,
        'is_claimant': is_claimant,
        'is_staff': is_staff,
        'can_view_private_answers': can_view_private_answers,
        'history_logs': history_logs,
        'competing_claims_count': competing_claims_count,
    })


@login_required
def claim_withdraw_view(request, pk):
    """Allows claimant to withdraw their pending claim."""
    claim = get_object_or_404(Claim, pk=pk)

    if not claim.can_withdraw(request.user):
        raise PermissionDenied("You cannot withdraw this claim.")

    if request.method == 'POST':
        old_status = claim.status
        claim.status = Claim.STATUS_WITHDRAWN
        claim.decision_reason = "Withdrawn voluntarily by claimant."
        claim.save(update_fields=['status', 'decision_reason', 'updated_at'])

        ClaimStatusHistory.objects.create(
            claim=claim,
            changed_by=request.user,
            old_status=old_status,
            new_status=Claim.STATUS_WITHDRAWN,
            reason="Claimant chose to withdraw their claim."
        )

        NotificationService.notify_claim_status_changed(
            claim,
            old_status,
            Claim.STATUS_WITHDRAWN,
            "Withdrawn by claimant."
        )

        messages.info(request, "Your ownership claim has been withdrawn.")
        return redirect('items:dashboard')

    return render(request, 'items/claim_confirm_withdraw.html', {'claim': claim})


@login_required
def my_claims_list_view(request):
    """View all claims submitted by the logged in user."""
    claims = Claim.objects.filter(claimant=request.user).select_related('item__category', 'item__location')

    paginator = Paginator(claims, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'items/my_claims.html', {
        'page_obj': page_obj,
    })


# --------------------------------------------------------------------------
# STEP 2: STAFF / ADMIN CLAIMS MODERATION & MULTIPLE CLAIMANTS
# --------------------------------------------------------------------------

@login_required
def admin_claims_list_view(request):
    """
    Campus staff review queue for all ownership claims.
    Filters by status, risk flags, and highlights items with multiple competing claims.
    """
    if not getattr(request.user, 'is_staff_member', False):
        raise PermissionDenied("Only campus staff and administrators can access the claims review queue.")

    status_filter = request.GET.get('status', '')
    flagged_only = request.GET.get('flagged', '') == 'true'
    q = request.GET.get('q', '').strip()

    claims = Claim.objects.all().select_related(
        'item', 'claimant', 'reviewed_by', 'item__category'
    )

    if status_filter:
        claims = claims.filter(status=status_filter)
    if flagged_only:
        claims = claims.filter(fraud_risk_score__gte=30)
    if q:
        claims = claims.filter(
            Q(item__title__icontains=q) |
            Q(claimant__username__icontains=q) |
            Q(claimant__student_id__icontains=q) |
            Q(identifying_details__icontains=q)
        )

    paginator = Paginator(claims, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    stats = {
        'total': Claim.objects.count(),
        'pending': Claim.objects.filter(status=Claim.STATUS_PENDING).count(),
        'under_review': Claim.objects.filter(status=Claim.STATUS_UNDER_REVIEW).count(),
        'approved': Claim.objects.filter(status=Claim.STATUS_APPROVED).count(),
        'flagged': Claim.objects.filter(fraud_risk_score__gte=30).count(),
    }

    return render(request, 'items/admin_claims_list.html', {
        'page_obj': page_obj,
        'stats': stats,
        'current_status': status_filter,
        'flagged_only': flagged_only,
        'q': q,
        'status_choices': Claim.STATUS_CHOICES,
    })


@login_required
def admin_claim_review_view(request, pk):
    """
    Review a specific claim with explainable risk indicators.
    Shows competing claims on the same item to prevent conflicting final ownership decisions.
    """
    if not getattr(request.user, 'is_staff_member', False):
        raise PermissionDenied("Only campus staff and administrators can review claims.")

    claim = get_object_or_404(
        Claim.objects.select_related('item', 'claimant', 'reviewed_by'),
        pk=pk
    )

    # Fetch other competing claims on the same item
    competing_claims = Claim.objects.filter(
        item=claim.item
    ).exclude(pk=claim.pk).select_related('claimant')

    # Check if another claim is already approved for this item
    already_approved_claim = Claim.objects.filter(
        item=claim.item,
        status=Claim.STATUS_APPROVED
    ).exclude(pk=claim.pk).first()

    if request.method == 'POST':
        form = ClaimReviewForm(request.POST, instance=claim)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            decision_reason = form.cleaned_data['decision_reason']
            admin_notes = form.cleaned_data['admin_notes']

            # Conflict prevention check
            if new_status == Claim.STATUS_APPROVED and already_approved_claim:
                messages.error(
                    request,
                    f"Conflict Blocked: Claim #{already_approved_claim.pk} is already approved for this item. "
                    "You must reject or revoke the previous approval before approving another claimant."
                )
                return render(request, 'items/admin_claim_review.html', {
                    'claim': claim,
                    'form': form,
                    'competing_claims': competing_claims,
                    'already_approved_claim': already_approved_claim,
                })

            old_status = claim.status
            claim.status = new_status
            claim.decision_reason = decision_reason
            claim.admin_notes = admin_notes
            claim.reviewed_by = request.user
            claim.reviewed_at = timezone.now()
            claim.save()

            # Update item status if approved
            if new_status == Claim.STATUS_APPROVED:
                claim.item.status = Item.STATUS_CLAIMED
                claim.item.save(update_fields=['status', 'updated_at'])

                ItemStatusHistory.objects.create(
                    item=claim.item,
                    changed_by=request.user,
                    old_status=claim.item.status,
                    new_status=Item.STATUS_CLAIMED,
                    remarks=f"Ownership claim #{claim.pk} approved for {claim.claimant.display_name}."
                )

            # Send in-app notification to claimant
            NotificationService.notify_claim_status_changed(
                claim,
                old_status,
                new_status,
                decision_reason
            )

            messages.success(request, f"Claim #{claim.pk} status updated to '{claim.get_status_display()}'.")
            return redirect('items:admin_claims_list')
    else:
        form = ClaimReviewForm(instance=claim)

    return render(request, 'items/admin_claim_review.html', {
        'claim': claim,
        'form': form,
        'competing_claims': competing_claims,
        'already_approved_claim': already_approved_claim,
    })


# --------------------------------------------------------------------------
# STEP 2: NOTIFICATIONS
# --------------------------------------------------------------------------

@login_required
def notifications_list_view(request):
    """View and manage in-app notifications for the logged in user."""
    notifications = Notification.objects.filter(recipient=request.user)

    # Mark as read if POST
    if request.method == 'POST':
        unread = notifications.filter(is_read=False)
        unread.update(is_read=True)
        messages.info(request, "All notifications marked as read.")
        return redirect('items:notifications')

    paginator = Paginator(notifications, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    unread_count = notifications.filter(is_read=False).count()

    return render(request, 'items/notifications.html', {
        'page_obj': page_obj,
        'unread_count': unread_count,
    })


# --------------------------------------------------------------------------
# STEP 3: RECOVERY, HANDOVER, RECEIPTS, MESSAGING & REWARDS
# --------------------------------------------------------------------------

@login_required
def handover_initiate_view(request, claim_pk):
    """
    Initiates physical recovery handover for an approved claim.
    Generates salted SHA-256 hashed 6-digit OTP and notifies participants.
    """
    claim = get_object_or_404(Claim.objects.select_related('item', 'claimant', 'item__user'), pk=claim_pk)

    if claim.status != Claim.STATUS_APPROVED:
        messages.error(request, "A physical handover can only be initiated for an approved ownership claim.")
        return redirect('items:claim_detail', pk=claim.pk)

    # Permission check: claimant, item reporter, or staff
    is_claimant = (request.user == claim.claimant)
    is_reporter = (request.user == claim.item.user)
    is_staff = getattr(request.user, 'is_staff_member', False)

    if not (is_claimant or is_reporter or is_staff):
        raise PermissionDenied("You do not have permission to initiate handover for this claim.")

    # Redirect if handover already active
    existing_handover = getattr(claim, 'handover', None)
    if existing_handover:
        return redirect('items:handover_detail', pk=existing_handover.pk)

    if request.method == 'POST':
        form = HandoverInitiateForm(request.POST)
        if form.is_valid():
            # Determine holder (the person currently in possession of the found item)
            holder = claim.item.user if (claim.item.user and claim.item.user != claim.claimant) else request.user

            handover = Handover(
                claim=claim,
                item=claim.item,
                claimant=claim.claimant,
                held_by=holder,
                handover_location=form.cleaned_data['handover_location'],
                handover_notes=form.cleaned_data.get('handover_notes', ''),
            )
            raw_otp = handover.generate_otp(expiry_minutes=30)
            handover.save()

            # Dispatches in-app and modular external alerts
            NotificationService.notify_handover_initiated(handover)

            # Store in session flash for claimant
            request.session[f'handover_otp_{handover.pk}'] = raw_otp

            messages.success(
                request,
                "Handover initiated! A secure, time-limited 6-digit OTP has been generated for identity verification."
            )
            return redirect('items:handover_detail', pk=handover.pk)
    else:
        form = HandoverInitiateForm()

    return render(request, 'items/handover_initiate.html', {
        'claim': claim,
        'form': form,
    })


@login_required
def handover_detail_view(request, pk):
    """
    Private handover management page.
    - Verified Claimant: Views the time-limited 6-digit OTP to show during exchange.
    - Item Holder / Staff: Enters claimant's OTP with maximum 5 attempts.
    Never exposes OTP on public item pages.
    """
    handover = get_object_or_404(
        Handover.objects.select_related('claim', 'item', 'item__category', 'item__location', 'claimant', 'held_by', 'receipt'),
        pk=pk
    )

    is_claimant = (request.user == handover.claimant)
    is_holder = (request.user == handover.held_by)
    is_staff = getattr(request.user, 'is_staff_member', False)

    if not (is_claimant or is_holder or is_staff):
        raise PermissionDenied("You are not authorized to view this handover.")

    # Handle actions
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'regenerate_otp':
            if not (is_claimant or is_staff):
                raise PermissionDenied("Only the claimant or campus staff can regenerate an OTP.")

            if handover.status != Handover.STATUS_INITIATED:
                messages.error(request, f"Cannot refresh OTP: handover is already {handover.get_status_display()}.")
            else:
                new_otp = handover.generate_otp(expiry_minutes=30)
                handover.save(update_fields=['otp_hash', 'otp_salt', 'otp_expires_at', 'attempts_count', 'status', 'updated_at'])
                request.session[f'handover_otp_{handover.pk}'] = new_otp
                messages.success(request, "New 6-digit verification OTP generated (valid for 30 minutes).")
            return redirect('items:handover_detail', pk=handover.pk)

        elif action == 'verify_otp':
            # Claimant cannot verify their own OTP
            if is_claimant and not is_staff:
                messages.error(request, "As the claimant, please present your 6-digit code to the campus officer / finder to verify.")
                return redirect('items:handover_detail', pk=handover.pk)

            verify_form = OTPVerificationForm(request.POST)
            if verify_form.is_valid():
                entered_otp = verify_form.cleaned_data['otp_code']
                success, msg = handover.verify_otp(entered_otp)

                if success:
                    # Award reward points and evaluate achievement badges
                    RewardService.award_handover_reward(handover)
                    NotificationService.notify_otp_verification_result(handover, success=True)
                    messages.success(request, msg)

                    receipt = getattr(handover, 'receipt', None)
                    if receipt:
                        return redirect('items:recovery_receipt', pk=receipt.pk)
                    return redirect('items:handover_detail', pk=handover.pk)
                else:
                    NotificationService.notify_otp_verification_result(handover, success=False, message=msg)
                    messages.error(request, msg)
                    return redirect('items:handover_detail', pk=handover.pk)
            else:
                messages.error(request, "Please enter a valid 6-digit numerical OTP.")
                return redirect('items:handover_detail', pk=handover.pk)

        elif action == 'cancel_handover':
            if not (is_holder or is_staff):
                raise PermissionDenied("Only the item holder or staff can cancel this handover.")
            if handover.status == Handover.STATUS_INITIATED:
                handover.status = Handover.STATUS_CANCELLED
                handover.save(update_fields=['status', 'updated_at'])
                messages.info(request, "Handover has been cancelled.")
            return redirect('items:handover_detail', pk=handover.pk)

    verify_form = OTPVerificationForm()
    claimant_otp = request.session.get(f'handover_otp_{handover.pk}') if (is_claimant or is_staff) else None
    receipt = getattr(handover, 'receipt', None)
    is_expired = timezone.now() > handover.otp_expires_at if handover.otp_expires_at else False
    reward_tx = handover.reward_transactions.filter(user=request.user).first() or handover.reward_transactions.first()

    return render(request, 'items/handover_detail.html', {
        'handover': handover,
        'is_claimant': is_claimant,
        'is_holder': is_holder,
        'is_staff': is_staff,
        'claimant_otp': claimant_otp,
        'verify_form': verify_form,
        'receipt': receipt,
        'is_expired': is_expired,
        'reward_tx': reward_tx,
        'now': timezone.now(),
    })


@login_required
def recovery_receipt_view(request, pk):
    """
    View and print digital recovery receipt.
    Immutable proof containing cryptographic digital signature, item code,
    and masked participant names.
    """
    receipt = get_object_or_404(
        RecoveryReceipt.objects.select_related('handover__item', 'handover__claimant', 'handover__held_by'),
        pk=pk
    )

    is_claimant = (request.user == receipt.handover.claimant)
    is_holder = (request.user == receipt.handover.held_by)
    is_staff = getattr(request.user, 'is_staff_member', False)

    if not (is_claimant or is_holder or is_staff):
        raise PermissionDenied("You do not have permission to access this recovery receipt.")

    return render(request, 'items/recovery_receipt.html', {
        'receipt': receipt,
        'handover': receipt.handover,
        'item': receipt.handover.item,
    })


def recovery_timeline_view(request, pk):
    """Visual recovery timeline for an item from report to recovery."""
    item = get_object_or_404(
        Item.objects.select_related('category', 'location', 'user', 'institution'),
        pk=pk
    )
    timeline_events = build_item_timeline(item)

    return render(request, 'items/recovery_timeline.html', {
        'item': item,
        'timeline_events': timeline_events,
    })


def item_tag_view(request, pk):
    """
    Printable item identification tag page.
    Displays safe item reference code, category, campus location, and return instructions
    without QR code matrices or private contact details.
    """
    item = get_object_or_404(
        Item.objects.select_related('category', 'location', 'institution'),
        pk=pk
    )
    tag_context = TagService.generate_tag_context(item, request=request)

    return render(request, 'items/item_tag.html', tag_context)


# Backward compatibility alias
qr_tag_view = item_tag_view


@login_required
def item_conversation_view(request, pk):
    """
    Directs user into an anonymous coordination chat thread for the item.
    Protects private phone number and email addresses.
    Enforces participant authorization: only reporter, active claimants, or staff.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    item = get_object_or_404(Item.objects.select_related('user'), pk=pk)

    is_reporter = (item.user == request.user)
    is_staff = getattr(request.user, 'is_staff_member', False)
    user_claim = item.claims.filter(claimant=request.user).first()
    is_claimant = (user_claim is not None)

    # Prevent unauthorized users from reading or starting messages
    if not (is_reporter or is_claimant or is_staff):
        messages.info(request, "To coordinate securely with the item custodian or finder, please submit an ownership claim first.")
        return redirect('items:item_claim', pk=item.pk)

    claim = None
    if is_reporter:
        # Reporter coordinates with verified/approved claimant, or first active claimant
        approved_claim = item.claims.filter(status=Claim.STATUS_APPROVED).first()
        claim = approved_claim or item.claims.first()
        if not claim:
            messages.info(
                request,
                "No ownership claim has been submitted for this item yet. Coordination chat will unlock once a claimant submits proof."
            )
            return redirect('items:item_detail', pk=item.pk)
        counterpart = claim.claimant
    elif is_claimant:
        # Claimant coordinates with the item reporter or staff
        claim = user_claim
        if item.user and item.user != request.user:
            counterpart = item.user
        else:
            counterpart = User.objects.filter(role__in=['staff', 'admin'], is_active=True).first()
            if not counterpart:
                messages.error(request, "Unable to establish conversation: campus desk staff is currently unavailable.")
                return redirect('items:item_detail', pk=item.pk)
    else:
        # Staff coordinator: coordinate with the reporter or claimant
        claim = item.claims.filter(status=Claim.STATUS_APPROVED).first() or item.claims.first()
        counterpart = item.user if item.user else (claim.claimant if claim else None)
        if not counterpart or counterpart == request.user:
            counterpart = User.objects.filter(is_active=True).exclude(pk=request.user.pk).first()
            if not counterpart:
                messages.error(request, "No recipient available for this coordination thread.")
                return redirect('items:item_detail', pk=item.pk)

    if request.user == counterpart:
        messages.warning(request, "You cannot establish a coordination conversation with yourself.")
        return redirect('items:item_detail', pk=item.pk)

    try:
        conv = CommunicationService.get_or_create_conversation(item, request.user, counterpart, claim=claim)
        return redirect('items:conversation_detail', pk=conv.pk)
    except Exception as e:
        messages.error(request, f"Unable to establish conversation thread: {str(e)}")
        return redirect('items:item_detail', pk=item.pk)


@login_required
def conversation_detail_view(request, pk):
    """Private anonymous messaging thread between authorized participants."""
    conv = get_object_or_404(
        ItemConversation.objects.select_related('item', 'participant_1', 'participant_2'),
        pk=pk
    )

    if not conv.can_access(request.user):
        raise PermissionDenied("You do not have access to this conversation.")

    if request.method == 'POST':
        form = AnonymousMessageForm(request.POST)
        if form.is_valid():
            CommunicationService.send_message(conv, request.user, form.cleaned_data['message_text'])
            messages.success(request, "Secure message dispatched.")
            return redirect('items:conversation_detail', pk=conv.pk)
    else:
        form = AnonymousMessageForm()

    messages_qs = conv.messages.select_related('sender', 'flagged_by').order_by('created_at')
    abuse_form = ReportAbuseForm()

    counterpart = conv.participant_2 if request.user == conv.participant_1 else conv.participant_1

    return render(request, 'items/conversation.html', {
        'conversation': conv,
        'item': conv.item,
        'messages_list': messages_qs,
        'counterpart': counterpart,
        'form': form,
        'abuse_form': abuse_form,
    })


@login_required
def message_report_abuse_view(request, pk):
    """Flags an abusive message for administrative review."""
    msg = get_object_or_404(ConversationMessage, pk=pk)

    if request.method == 'POST':
        form = ReportAbuseForm(request.POST)
        if form.is_valid():
            CommunicationService.report_abuse(msg, request.user, form.cleaned_data['abuse_reason'])
            messages.warning(request, "Message flagged for campus administration review.")

    return redirect('items:conversation_detail', pk=msg.conversation.pk)


def leaderboard_view(request):
    """
    Campus Recovery Citizenship Leaderboard.
    Displays privacy-conscious student rankings, points, and achievement badges.
    """
    RewardService.ensure_default_badges()

    institution = None
    if request.user.is_authenticated and hasattr(request.user, 'institution') and request.user.institution:
        institution = request.user.institution

    leaderboard = RewardService.get_leaderboard(institution=institution, limit=25)
    all_badges = Badge.objects.all().order_by('points_threshold')

    user_transactions = None
    user_badges = []
    user_rank = None

    if request.user.is_authenticated:
        user_transactions = request.user.reward_transactions.select_related('item', 'handover')[:10]
        user_badges = [ub.badge for ub in request.user.badges.select_related('badge')]
        for entry in leaderboard:
            if entry['user_id'] == request.user.pk:
                user_rank = entry['rank']
                break

    return render(request, 'items/leaderboard.html', {
        'leaderboard': leaderboard,
        'all_badges': all_badges,
        'user_transactions': user_transactions,
        'user_badges': user_badges,
        'user_rank': user_rank,
    })


@login_required
def notification_preferences_view(request):
    """User-configurable notification channel preferences."""
    pref, _ = NotificationPreference.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = NotificationPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            messages.success(request, "Your notification preferences have been saved.")
            return redirect('items:notification_preferences')
    else:
        form = NotificationPreferenceForm(instance=pref)

    return render(request, 'items/notification_preferences.html', {
        'form': form,
    })

