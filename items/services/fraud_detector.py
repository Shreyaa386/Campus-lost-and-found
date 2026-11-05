"""
Fraud Detection & Risk Analysis Service for CampusCare.
Calculates explainable risk indicators for claims and reports without automatically
banning users. Highlights potential abuse for campus administrator and security review.
"""

from datetime import timedelta
from difflib import SequenceMatcher
from django.utils import timezone


class FraudDetector:
    """
    Evaluates claims and reports for suspicious patterns, claim velocity,
    rejection rates, and text mirroring.
    """

    @classmethod
    def analyze_claim_risk(cls, claimant, item, identifying_details):
        """
        Analyzes a proposed claim.
        Returns:
            (risk_score: int [0 - 100], risk_flags: list of dicts)
        """
        from items.models import Claim

        risk_score = 0
        risk_flags = []
        now = timezone.now()

        # ----------------------------------------------------
        # 1. 24-Hour Claim Velocity
        # ----------------------------------------------------
        recent_24h_claims = Claim.objects.filter(
            claimant=claimant,
            created_at__gte=now - timedelta(hours=24)
        ).count()

        if recent_24h_claims >= 4:
            risk_score += 35
            risk_flags.append({
                'rule': 'high_24h_velocity',
                'severity': 'high',
                'title': 'High 24h Claim Velocity',
                'description': f"Claimant has submitted {recent_24h_claims} claims in the past 24 hours."
            })
        elif recent_24h_claims >= 2:
            risk_score += 15
            risk_flags.append({
                'rule': 'moderate_24h_velocity',
                'severity': 'medium',
                'title': 'Multiple Claims in 24h',
                'description': f"Claimant has submitted {recent_24h_claims} claims in the past 24 hours."
            })

        # ----------------------------------------------------
        # 2. 7-Day Multi-Category Claim Frequency
        # ----------------------------------------------------
        recent_7d_claims = Claim.objects.filter(
            claimant=claimant,
            created_at__gte=now - timedelta(days=7)
        )
        count_7d = recent_7d_claims.count()
        distinct_categories = recent_7d_claims.values_list('item__category_id', flat=True).distinct().count()

        if count_7d >= 6 and distinct_categories >= 3:
            risk_score += 25
            risk_flags.append({
                'rule': 'multi_category_surge',
                'severity': 'high',
                'title': 'Broad Multi-Category Claims',
                'description': f"Claimant has submitted {count_7d} claims across {distinct_categories} different categories this week."
            })

        # ----------------------------------------------------
        # 3. Previous Claim Rejection History
        # ----------------------------------------------------
        rejected_count = Claim.objects.filter(
            claimant=claimant,
            status=Claim.STATUS_REJECTED
        ).count()

        if rejected_count >= 3:
            risk_score += 25
            risk_flags.append({
                'rule': 'repeated_rejections',
                'severity': 'high',
                'title': 'Frequent Prior Rejections',
                'description': f"Claimant has {rejected_count} previously rejected ownership claims on record."
            })
        elif rejected_count >= 1:
            risk_score += 10
            risk_flags.append({
                'rule': 'prior_rejection',
                'severity': 'low',
                'title': 'Prior Rejection Recorded',
                'description': f"Claimant has had an ownership claim rejected in the past."
            })

        # ----------------------------------------------------
        # 4. Text Mirroring of Public Description
        # ----------------------------------------------------
        # If claimant's private text simply duplicates public description
        if item.description and identifying_details:
            ratio = SequenceMatcher(
                None,
                item.description.lower().strip(),
                identifying_details.lower().strip()
            ).ratio()

            if ratio >= 0.70:
                risk_score += 30
                risk_flags.append({
                    'rule': 'public_text_mirroring',
                    'severity': 'high',
                    'title': 'Public Text Mirroring',
                    'description': "Claim details closely mirror the public description rather than offering private identifying details."
                })

        # ----------------------------------------------------
        # 5. Brief or Low-Effort Verification Details
        # ----------------------------------------------------
        words = identifying_details.split() if identifying_details else []
        if len(words) < 3:
            risk_score += 15
            risk_flags.append({
                'rule': 'sparse_identifying_details',
                'severity': 'medium',
                'title': 'Minimal Identifying Details',
                'description': "Provided identifying proof contains fewer than 3 words.",
                'reason': "Provided identifying proof contains fewer than 3 words."
            })

        # ----------------------------------------------------
        # 6. Step 5: Rapid Post-Publication Claim (Under 5 mins)
        # ----------------------------------------------------
        if hasattr(item, 'created_at') and item.created_at:
            delta_seconds = (now - item.created_at).total_seconds()
            if 0 <= delta_seconds < 300:  # < 5 minutes
                risk_score += 20
                risk_flags.append({
                    'rule': 'rapid_submission_velocity',
                    'severity': 'medium',
                    'title': 'Rapid Post-Publication Claim',
                    'description': f"Claim submitted within {int(delta_seconds // 60)} minutes of report publication.",
                    'reason': f"Claim submitted within {int(delta_seconds // 60)} minutes of report publication."
                })

        # ----------------------------------------------------
        # 7. Step 5: Cross-Institution Origin Mismatch
        # ----------------------------------------------------
        if hasattr(claimant, 'institution') and hasattr(item, 'institution'):
            if claimant.institution and item.institution and claimant.institution != item.institution:
                if not getattr(item, 'is_cross_campus_visible', False):
                    risk_score += 25
                    risk_flags.append({
                        'rule': 'cross_institution_unauthorized',
                        'severity': 'high',
                        'title': 'Cross-Institution Mismatch',
                        'description': f"Claimant is from '{claimant.institution.short_name or claimant.institution.name}', but item belongs to '{item.institution.short_name or item.institution.name}' without cross-campus authorization.",
                        'reason': "Claimant institution does not match item institution."
                    })

        # Normalize flags to ensure 'reason' key is always present
        for f in risk_flags:
            if 'reason' not in f:
                f['reason'] = f.get('description', f.get('title', 'Risk indicator flagged.'))

        # Clamp risk score between 0 and 100
        final_score = min(100, max(0, risk_score))
        return final_score, risk_flags

    @classmethod
    def get_risk_label(cls, score):
        """Returns human-friendly category and badge class for a risk score."""
        if score >= 60:
            return "High Review Caution", "badge-danger", "#ef4444"
        elif score >= 30:
            return "Moderate Caution", "badge-warning", "#f59e0b"
        else:
            return "Standard Review", "badge-open", "#2563eb"

