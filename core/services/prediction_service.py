"""
Lost-Item Trend and Hotspot Prediction Service for CampusCare.
Analyzes aggregate historical incident report distributions across categories,
campus facilities, days of the week, and academic cycle phases.
Generates explainable, privacy-safe heuristic forecasts with explicit confidence
ratings and prominent distinction between empirical data and statistical projections.
"""

from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone


class PredictionService:
    """
    Computes heuristic risk projections and preventative patrol scheduling metrics.
    """

    DISCLAIMER = (
        "Preventative Security Guidance: Projections are heuristic risk estimates computed "
        "from aggregate historical frequency and temporal density. They do not claim certainty "
        "and are intended solely for preventative campus patrol scheduling and lost-and-found awareness."
    )

    @classmethod
    def get_predictions(cls, institution=None, days_lookback: int = 90) -> dict:
        """
        Analyzes historical reports over lookback period and computes:
        1. Category Vulnerability Projections
        2. Campus Location Risk Heat Indices
        3. Day-of-Week Incident Probabilities
        4. Preventative Security Patrol Recommendations
        """
        from core.models import CampusLocation, Category
        from items.models import Item

        since = timezone.now() - timedelta(days=days_lookback)
        items_qs = Item.objects.filter(created_at__gte=since)
        if institution:
            items_qs = items_qs.filter(institution=institution)

        total_reports = items_qs.count()

        # 1. Category Distribution & Projections
        category_data = (
            items_qs.values('category__id', 'category__name', 'category__icon')
            .annotate(
                total=Count('id'),
                lost_count=Count('id', filter=Q(report_type=Item.REPORT_TYPE_LOST)),
                found_count=Count('id', filter=Q(report_type=Item.REPORT_TYPE_FOUND))
            )
            .order_by('-total')
        )

        categories_summary = []
        for c in category_data:
            cat_name = c['category__name'] or "General Belongings"
            count = c['total']
            percentage = round((count / total_reports * 100), 1) if total_reports > 0 else 0

            # Heuristic projection: Risk level based on historical proportion
            if percentage >= 25:
                risk_level = "High Risk"
                confidence = 88
                trend_forecast = "Projected continued high loss rate during peak student transit hours."
            elif percentage >= 12:
                risk_level = "Moderate Risk"
                confidence = 74
                trend_forecast = "Moderate weekly incident rate expected."
            else:
                risk_level = "Low Risk"
                confidence = 62
                trend_forecast = "Infrequent occurrences; sporadic loss patterns."

            categories_summary.append({
                'category_id': c['category__id'],
                'category_name': cat_name,
                'category_icon': c['category__icon'] or 'fa-box',
                'historical_count': count,
                'lost_count': c['lost_count'],
                'found_count': c['found_count'],
                'share_pct': percentage,
                'projected_risk': risk_level,
                'confidence_pct': confidence,
                'forecast': trend_forecast
            })

        # 2. Location Hotspot Vulnerability Index
        location_data = (
            items_qs.values('location__id', 'location__name', 'location__building')
            .annotate(
                total=Count('id'),
                lost_count=Count('id', filter=Q(report_type=Item.REPORT_TYPE_LOST)),
                found_count=Count('id', filter=Q(report_type=Item.REPORT_TYPE_FOUND))
            )
            .order_by('-total')
        )

        locations_summary = []
        for loc in location_data:
            loc_name = loc['location__name'] or "General Campus"
            count = loc['total']
            pct = round((count / total_reports * 100), 1) if total_reports > 0 else 0

            if pct >= 20:
                patrol_priority = "Priority 1 (Hourly Check)"
                vulnerability_score = 90
            elif pct >= 10:
                patrol_priority = "Priority 2 (Daily Routine)"
                vulnerability_score = 65
            else:
                patrol_priority = "Priority 3 (Standard)"
                vulnerability_score = 35

            locations_summary.append({
                'location_id': loc['location__id'],
                'location_name': loc_name,
                'building': loc['location__building'] or "Main Campus",
                'historical_count': count,
                'lost_count': loc['lost_count'],
                'found_count': loc['found_count'],
                'share_pct': pct,
                'vulnerability_score': vulnerability_score,
                'patrol_recommendation': patrol_priority,
            })

        # 3. Day of Week Patterns (Heuristic distribution)
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_counts = {i: 0 for i in range(7)}
        for dt in items_qs.values_list('date_lost_or_found', flat=True):
            if dt:
                day_counts[dt.weekday()] += 1

        day_patterns = []
        for day_idx in range(7):
            cnt = day_counts[day_idx]
            d_pct = round((cnt / total_reports * 100), 1) if total_reports > 0 else 0
            day_patterns.append({
                'day_name': day_names[day_idx],
                'count': cnt,
                'percentage': d_pct,
                'risk_indicator': "Peak Incident Day" if d_pct >= 20 else ("Moderate" if d_pct >= 10 else "Low")
            })

        # 4. Actionable Security Recommendations
        top_category = categories_summary[0]['category_name'] if categories_summary else "Electronics"
        top_location = locations_summary[0]['location_name'] if locations_summary else "Central Library"

        recommendations = [
            f"Increase physical patrol frequency at **{top_location}** during student changeover periods.",
            f"Display preventative lost-and-found awareness signage regarding **{top_category}** in high-density facilities.",
            "Schedule proactive lost property drop-box clearances on Monday and Friday afternoons.",
            "Verify all found electronic devices are logged at Campus Security within 24 hours of discovery."
        ]

        return {
            'disclaimer': cls.DISCLAIMER,
            'lookback_days': days_lookback,
            'total_analyzed_reports': total_reports,
            'categories_projection': categories_summary,
            'locations_projection': locations_summary,
            'day_patterns': day_patterns,
            'recommendations': recommendations,
            'generated_at': timezone.now().strftime('%B %d, %Y %H:%M')
        }

