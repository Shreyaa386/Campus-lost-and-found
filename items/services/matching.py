"""
Smart Matching Engine for CampusCare.
Calculates explainable weighted similarity scores between Lost reports and Found reports.
Compares category, title, description, location, date proximity, and visual similarity.
"""

import re
from datetime import timedelta
from difflib import SequenceMatcher
from django.db.models import Q
from .image_similarity import ImageSimilarityService

# Common stopwords to ignore during text tokenization
STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'he', 'in', 'is', 'it', 'its', 'my', 'mine', 'of', 'on',
    'or', 'that', 'the', 'to', 'was', 'were', 'will', 'with', 'i',
    'lost', 'found', 'item', 'please', 'help', 'near', 'around', 'color',
    'have', 'had', 'this', 'there', 'me', 'some', 'any'
}


class MatchingService:
    """
    Modular, explainable lost-and-found matching service.
    """

    @classmethod
    def _tokenize(cls, text):
        """Extract clean alphanumeric words of length >= 2, excluding stopwords."""
        if not text:
            return set()
        words = re.findall(r'\b[a-zA-Z0-9_-]{2,}\b', text.lower())
        return {w for w in words if w not in STOPWORDS}

    @classmethod
    def compute_similarity(cls, item_a, item_b):
        """
        Computes match score and detailed reasons between two reports.
        item_a and item_b should ideally be one Lost and one Found.
        Returns:
            dict containing:
                score (float): 0.0 to 100.0
                category_score (float)
                text_score (float)
                location_score (float)
                date_score (float)
                image_score (float)
                reasons (list of str): Human-readable breakdown bullets
        """
        # Determine which is lost and which is found for date logic
        if item_a.report_type == 'lost' and item_b.report_type == 'found':
            lost_item, found_item = item_a, item_b
        elif item_a.report_type == 'found' and item_b.report_type == 'lost':
            lost_item, found_item = item_b, item_a
        else:
            # Both same type — generally not matched, but compute similarity symmetrically
            lost_item, found_item = item_a, item_b

        reasons = []

        # ----------------------------------------------------
        # 1. Category Matching (Weight: 25.0)
        # ----------------------------------------------------
        category_score = 0.0
        if item_a.category_id == item_b.category_id:
            category_score = 25.0
            reasons.append(f"Category Match: Both items are categorized as '{item_a.category.name}' (+25%).")
        else:
            reasons.append(f"Category Difference: '{item_a.category.name}' vs '{item_b.category.name}' (0%).")

        # ----------------------------------------------------
        # 2. Textual & Keyword Similarity (Weight: 30.0)
        # ----------------------------------------------------
        tokens_a_title = cls._tokenize(item_a.title)
        tokens_b_title = cls._tokenize(item_b.title)
        tokens_a_all = tokens_a_title | cls._tokenize(item_a.description)
        tokens_b_all = tokens_b_title | cls._tokenize(item_b.description)

        # Title similarity (SequenceMatcher + Token overlap)
        title_seq_ratio = SequenceMatcher(None, item_a.title.lower(), item_b.title.lower()).ratio()
        title_overlap = tokens_a_title & tokens_b_title
        all_overlap = tokens_a_all & tokens_b_all

        # Jaccard index on all keywords
        union_all = tokens_a_all | tokens_b_all
        jaccard = (len(all_overlap) / len(union_all)) if union_all else 0.0

        # Weighted combination: 40% title sequence + 30% title overlap + 30% all keywords overlap
        raw_text_ratio = (title_seq_ratio * 0.4) + (min(1.0, len(title_overlap) / max(1, len(tokens_a_title))) * 0.3) + (jaccard * 0.3)
        text_score = round(min(30.0, raw_text_ratio * 30.0), 1)

        if all_overlap:
            matched_keywords = list(all_overlap)[:5]
            reasons.append(
                f"Keyword Overlap: Matched terms [{', '.join(matched_keywords)}] in title/description (+{text_score:.1f}%)."
            )
        elif text_score > 5.0:
            reasons.append(f"Textual Resemblance: Phrasing similarity detected (+{text_score:.1f}%).")
        else:
            reasons.append("Textual Difference: Few common identifying keywords found.")

        # ----------------------------------------------------
        # 3. Location Matching (Weight: 20.0)
        # ----------------------------------------------------
        location_score = 0.0
        if item_a.location_id and item_b.location_id:
            if item_a.location_id == item_b.location_id:
                location_score = 20.0
                reasons.append(f"Exact Location Match: Both reported at '{item_a.location.name}' (+20%).")
            elif item_a.location.building and item_b.location.building and (item_a.location.building.lower() == item_b.location.building.lower()):
                location_score = 15.0
                reasons.append(f"Same Building Match: Both reported in '{item_a.location.building}' (+15%).")
            else:
                location_score = 3.0
                reasons.append(f"Different Campus Locations: '{item_a.location.name}' vs '{item_b.location.name}' (+3%).")
        elif item_a.location_id or item_b.location_id:
            location_score = 5.0
            reasons.append("Partial Location Info: One report lacks a specific campus location (+5%).")
        else:
            location_score = 5.0
            reasons.append("General Campus: Neither report specified an exact room/building (+5%).")

        # Specific spot / details overlap bonus
        if item_a.location_details and item_b.location_details:
            spot_overlap = cls._tokenize(item_a.location_details) & cls._tokenize(item_b.location_details)
            if spot_overlap:
                location_score = min(20.0, location_score + 5.0)
                reasons.append(f"Spot Detail Match: Both noted '{', '.join(spot_overlap)}' (+bonus).")

        # ----------------------------------------------------
        # 4. Date Proximity (Weight: 15.0)
        # ----------------------------------------------------
        date_score = 0.0
        if lost_item.date_lost_or_found and found_item.date_lost_or_found:
            diff_days = (found_item.date_lost_or_found - lost_item.date_lost_or_found).days

            if 0 <= diff_days <= 1:
                date_score = 15.0
                reasons.append(f"Immediate Date Alignment: Found within 24-48 hours of loss (+15%).")
            elif 2 <= diff_days <= 3:
                date_score = 12.0
                reasons.append(f"Close Date Proximity: Found within {diff_days} days of loss (+12%).")
            elif 4 <= diff_days <= 7:
                date_score = 8.0
                reasons.append(f"Moderate Date Proximity: Found within a week of loss (+8%).")
            elif 8 <= diff_days <= 14:
                date_score = 5.0
                reasons.append(f"Date Proximity: Found within 2 weeks of loss (+5%).")
            elif diff_days < 0 and abs(diff_days) <= 1:
                # Discovered slightly before reported lost (e.g. reporting delay)
                date_score = 10.0
                reasons.append("Plausible Timeline: Discovered just prior to loss report submission (+10%).")
            else:
                date_score = 0.0
                reasons.append(f"Date Gap: Dates differ by {abs(diff_days)} days (0%).")
        else:
            date_score = 5.0
            reasons.append("Date Comparison: Incomplete date information.")

        # ----------------------------------------------------
        # 5. Image Similarity (Weight: 10.0)
        # ----------------------------------------------------
        image_score = 0.0
        if item_a.image and item_b.image:
            sim_score, label, explanation = ImageSimilarityService.compare_images(item_a.image, item_b.image)
            image_score = round(sim_score * 10.0, 1)
            reasons.append(f"Visual Image Comparison: {label} (+{image_score:.1f}%). {explanation}")
        else:
            # If one or both lack images, safely redistribute weight across text & location
            # so reports without images aren't penalized
            text_boost = round(text_score * (10.0 / 30.0) * 0.6, 1)
            loc_boost = round(location_score * (10.0 / 20.0) * 0.4, 1)
            text_score = min(35.0, text_score + text_boost)
            location_score = min(25.0, location_score + loc_boost)
            reasons.append("Image Comparison: One or both reports lack an image (weights normalized).")

        total_score = round(min(100.0, category_score + text_score + location_score + date_score + image_score), 1)

        return {
            'score': total_score,
            'category_score': category_score,
            'text_score': text_score,
            'location_score': location_score,
            'date_score': date_score,
            'image_score': image_score,
            'reasons': reasons,
        }

    @classmethod
    def find_matches_for_item(cls, item, min_score=35.0, limit=10):
        """
        Finds suggested matches for an item from opposite report type within
        the same institution.
        Updates/creates ItemMatch records in the database.
        Returns list of ItemMatch instances.
        """
        from items.models import Item, ItemMatch

        opposite_type = 'found' if item.report_type == 'lost' else 'lost'

        # Candidate pool: active opposite reports in the same institution
        candidates = Item.objects.filter(
            institution=item.institution,
            report_type=opposite_type,
            status=Item.STATUS_OPEN
        ).exclude(pk=item.pk).select_related('category', 'location', 'user')

        # Filter out matches previously dismissed by the user
        dismissed_target_ids = ItemMatch.objects.filter(
            source_item=item,
            status=ItemMatch.STATUS_DISMISSED
        ).values_list('matched_item_id', flat=True)

        if dismissed_target_ids:
            candidates = candidates.exclude(id__in=dismissed_target_ids)

        match_records = []

        for candidate in candidates:
            analysis = cls.compute_similarity(item, candidate)
            score = analysis['score']

            if score >= min_score:
                # Save or update ItemMatch record
                match_obj, created = ItemMatch.objects.update_or_create(
                    source_item=item,
                    matched_item=candidate,
                    defaults={
                        'score': score,
                        'category_score': analysis['category_score'],
                        'text_score': analysis['text_score'],
                        'location_score': analysis['location_score'],
                        'date_score': analysis['date_score'],
                        'image_score': analysis['image_score'],
                        'reasons': analysis['reasons'],
                        'status': ItemMatch.STATUS_SUGGESTED,
                    }
                )
                match_records.append(match_obj)

        # Sort descending by score
        match_records.sort(key=lambda m: m.score, reverse=True)
        return match_records[:limit]

