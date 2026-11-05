"""
Campus Heatmap Service for CampusCare.
Aggregates report locations using approved institutional GPS coordinates.
Protects student privacy by grouping strictly at campus building/facility granularity
with intensity scoring and category/time window filters.
"""

from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone


class HeatmapService:
    """
    Computes privacy-preserving geographic density clusters across campus locations.
    """

    @classmethod
    def get_heatmap_data(cls, institution=None, report_type='all', category_id=None, days: int = 30) -> dict:
        """
        Returns JSON-serializable aggregated hotspot coordinates and intensities.
        """
        from core.models import CampusLocation
        from items.models import Item

        # Filter items
        items_qs = Item.objects.filter(location__latitude__isnull=False, location__longitude__isnull=False)

        if institution:
            items_qs = items_qs.filter(institution=institution)

        if report_type in ['lost', 'found']:
            items_qs = items_qs.filter(report_type=report_type)

        if category_id:
            items_qs = items_qs.filter(category_id=category_id)

        if days and days > 0:
            since = timezone.now() - timedelta(days=days)
            items_qs = items_qs.filter(created_at__gte=since)

        # Aggregate by campus location
        aggregated = (
            items_qs.values(
                'location__id',
                'location__name',
                'location__building',
                'location__latitude',
                'location__longitude'
            )
            .annotate(
                total=Count('id'),
                lost_count=Count('id', filter=Q(report_type=Item.REPORT_TYPE_LOST)),
                found_count=Count('id', filter=Q(report_type=Item.REPORT_TYPE_FOUND)),
                recovered_count=Count('id', filter=Q(status=Item.STATUS_RETURNED))
            )
            .order_by('-total')
        )

        max_count = max([item['total'] for item in aggregated], default=1)
        if max_count == 0:
            max_count = 1

        points = []
        center_lat = 12.9716  # Default fallback (Bengaluru AIT)
        center_lng = 77.5946

        for row in aggregated:
            lat = row['location__latitude']
            lng = row['location__longitude']
            total = row['total']
            intensity = round(min(1.0, max(0.2, total / max_count)), 2)

            points.append({
                'location_id': row['location__id'],
                'name': row['location__name'],
                'building': row['location__building'],
                'lat': lat,
                'lng': lng,
                'count': total,
                'lost_count': row['lost_count'],
                'found_count': row['found_count'],
                'recovered_count': row['recovered_count'],
                'intensity': intensity,
            })

        if points:
            # Use centroid of points as map center
            center_lat = sum(p['lat'] for p in points) / len(points)
            center_lng = sum(p['lng'] for p in points) / len(points)

        return {
            'points': points,
            'total_hotspots': len(points),
            'max_density': max_count,
            'center': {'lat': center_lat, 'lng': center_lng},
        }

