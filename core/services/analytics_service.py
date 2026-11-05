"""
Analytics and Metrics Calculation Engine for CampusCare.
Computes KPIs, monthly/yearly recovery trends, resolution ratios,
location hotspots, category breakdown, and institution-specific intelligence.
"""

from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

User = get_user_model()


class AnalyticsService:
    """
    Computes aggregated performance, recovery, and security metrics.
    """

    @classmethod
    def get_kpis(cls, institution=None) -> dict:
        """
        Calculates core executive KPIs for the admin dashboard.
        """
        from core.models import SecurityAlert
        from items.models import Claim, Item, RewardTransaction

        users_qs = User.objects.all()
        items_qs = Item.objects.all()
        claims_qs = Claim.objects.all()
        alerts_qs = SecurityAlert.objects.all()
        rewards_qs = RewardTransaction.objects.all()

        if institution:
            users_qs = users_qs.filter(institution=institution)
            items_qs = items_qs.filter(institution=institution)
            claims_qs = claims_qs.filter(item__institution=institution)
            alerts_qs = alerts_qs.filter(institution=institution)
            rewards_qs = rewards_qs.filter(user__institution=institution)

        total_students = users_qs.filter(role=User.ROLE_STUDENT, is_active=True).count()
        faculty_and_staff = users_qs.filter(
            role__in=[User.ROLE_FACULTY, User.ROLE_STAFF, User.ROLE_ADMIN],
            is_active=True
        ).count()
        total_users = users_qs.count()

        lost_reports = items_qs.filter(report_type=Item.REPORT_TYPE_LOST).count()
        found_reports = items_qs.filter(report_type=Item.REPORT_TYPE_FOUND).count()
        total_reports = lost_reports + found_reports

        pending_claims = claims_qs.filter(
            status__in=[Claim.STATUS_PENDING, Claim.STATUS_UNDER_REVIEW]
        ).count()
        approved_claims = claims_qs.filter(status=Claim.STATUS_APPROVED).count()
        rejected_claims = claims_qs.filter(status=Claim.STATUS_REJECTED).count()

        recovered_items = items_qs.filter(status=Item.STATUS_RETURNED).count()
        unclaimed_items = items_qs.filter(
            report_type=Item.REPORT_TYPE_FOUND,
            status=Item.STATUS_OPEN
        ).count()
        expired_items = items_qs.filter(status=Item.STATUS_EXPIRED).count()
        archived_items = items_qs.filter(status=Item.STATUS_ARCHIVED).count()

        active_alerts = alerts_qs.filter(status=SecurityAlert.STATUS_PENDING).count()

        reward_points_issued = rewards_qs.aggregate(total=Sum('points'))['total'] or 0
        reward_tx_count = rewards_qs.count()

        recovery_rate = (recovered_items / total_reports * 100) if total_reports > 0 else 0.0

        return {
            'total_students': total_students,
            'faculty_and_staff': faculty_and_staff,
            'total_users': total_users,
            'lost_reports': lost_reports,
            'found_reports': found_reports,
            'total_reports': total_reports,
            'pending_claims': pending_claims,
            'approved_claims': approved_claims,
            'rejected_claims': rejected_claims,
            'recovered_items': recovered_items,
            'unclaimed_items': unclaimed_items,
            'expired_items': expired_items,
            'archived_items': archived_items,
            'active_alerts': active_alerts,
            'reward_points_issued': reward_points_issued,
            'reward_tx_count': reward_tx_count,
            'recovery_rate': round(recovery_rate, 1),
        }

    @classmethod
    def get_monthly_trends(cls, institution=None, months_count: int = 6) -> dict:
        """
        Generates month-by-month lost vs found vs recovered trend data.
        """
        from items.models import Item

        items_qs = Item.objects.all()
        if institution:
            items_qs = items_qs.filter(institution=institution)

        labels = []
        lost_data = []
        found_data = []
        recovered_data = []

        now = timezone.now()
        for i in range(months_count - 1, -1, -1):
            # Target month window
            target_date = now - timedelta(days=i * 30)
            year = target_date.year
            month = target_date.month
            month_label = target_date.strftime('%b %Y')
            labels.append(month_label)

            month_items = items_qs.filter(created_at__year=year, created_at__month=month)
            lost_data.append(month_items.filter(report_type=Item.REPORT_TYPE_LOST).count())
            found_data.append(month_items.filter(report_type=Item.REPORT_TYPE_FOUND).count())
            recovered_data.append(month_items.filter(status=Item.STATUS_RETURNED).count())

        return {
            'labels': labels,
            'lost_series': lost_data,
            'found_series': found_data,
            'recovered_series': recovered_data,
        }

    @classmethod
    def get_yearly_trends(cls, institution=None, years_count: int = 3) -> dict:
        """Computes annual recovery efficiency."""
        from items.models import Item

        items_qs = Item.objects.all()
        if institution:
            items_qs = items_qs.filter(institution=institution)

        current_year = timezone.now().year
        labels = []
        total_series = []
        recovered_series = []

        for yr in range(current_year - years_count + 1, current_year + 1):
            labels.append(str(yr))
            yr_items = items_qs.filter(created_at__year=yr)
            total_series.append(yr_items.count())
            recovered_series.append(yr_items.filter(status=Item.STATUS_RETURNED).count())

        return {
            'labels': labels,
            'total_series': total_series,
            'recovered_series': recovered_series,
        }

    @classmethod
    def get_category_stats(cls, institution=None) -> list:
        """Aggregates items breakdown across categories."""
        from core.models import Category
        from items.models import Item

        cats = Category.objects.filter(is_active=True)
        if institution:
            cats = cats.filter(Q(institution=institution) | Q(institution__isnull=True))

        items_qs = Item.objects.all()
        if institution:
            items_qs = items_qs.filter(institution=institution)

        results = []
        for c in cats:
            c_items = items_qs.filter(category=c)
            total = c_items.count()
            if total > 0 or True:
                results.append({
                    'category_id': c.pk,
                    'name': c.name,
                    'icon': c.icon,
                    'total': total,
                    'lost': c_items.filter(report_type=Item.REPORT_TYPE_LOST).count(),
                    'found': c_items.filter(report_type=Item.REPORT_TYPE_FOUND).count(),
                    'recovered': c_items.filter(status=Item.STATUS_RETURNED).count(),
                })
        results.sort(key=lambda x: x['total'], reverse=True)
        return results

    @classmethod
    def get_location_stats(cls, institution=None, limit: int = 10) -> list:
        """Identifies campus hot-spots for lost and found items."""
        from core.models import CampusLocation
        from items.models import Item

        locs = CampusLocation.objects.filter(is_active=True)
        if institution:
            locs = locs.filter(institution=institution)

        items_qs = Item.objects.all()
        if institution:
            items_qs = items_qs.filter(institution=institution)

        results = []
        for loc in locs:
            loc_items = items_qs.filter(location=loc)
            total = loc_items.count()
            results.append({
                'location_id': loc.pk,
                'name': loc.name,
                'building': loc.building,
                'total': total,
                'lost': loc_items.filter(report_type=Item.REPORT_TYPE_LOST).count(),
                'found': loc_items.filter(report_type=Item.REPORT_TYPE_FOUND).count(),
                'recovered': loc_items.filter(status=Item.STATUS_RETURNED).count(),
                'latitude': loc.latitude,
                'longitude': loc.longitude,
            })
        results.sort(key=lambda x: x['total'], reverse=True)
        return results[:limit]

    @classmethod
    def get_claim_moderation_stats(cls, institution=None) -> dict:
        """Computes claim review velocity, approval vs rejection ratio."""
        from items.models import Claim

        claims_qs = Claim.objects.all()
        if institution:
            claims_qs = claims_qs.filter(item__institution=institution)

        total = claims_qs.count()
        approved = claims_qs.filter(status=Claim.STATUS_APPROVED).count()
        rejected = claims_qs.filter(status=Claim.STATUS_REJECTED).count()
        withdrawn = claims_qs.filter(status=Claim.STATUS_WITHDRAWN).count()
        pending = claims_qs.filter(status__in=[Claim.STATUS_PENDING, Claim.STATUS_UNDER_REVIEW]).count()

        approval_rate = (approved / (approved + rejected) * 100) if (approved + rejected) > 0 else 0.0

        return {
            'total_claims': total,
            'approved': approved,
            'rejected': rejected,
            'withdrawn': withdrawn,
            'pending': pending,
            'approval_rate': round(approval_rate, 1),
        }

