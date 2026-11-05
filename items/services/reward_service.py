"""
Reward and Gamification Service for CampusCare.
Manages reward points ledger, duplicate transaction prevention,
milestone badges, and privacy-conscious campus leaderboards.
"""

import logging
from django.db import transaction
from django.utils.text import slugify

logger = logging.getLogger(__name__)


class RewardService:
    """
    Handles point calculation, ledger persistence, badge progression,
    and anti-fraud/anti-manipulation checks.
    """

    DEFAULT_BADGES = [
        {
            'slug': 'first-return',
            'name': 'Good Samaritan',
            'description': 'Safely returned your first found item to its rightful owner.',
            'icon': 'fa-handshake',
            'returns_threshold': 1,
            'points_threshold': 0,
        },
        {
            'slug': 'campus-guardian',
            'name': 'Campus Guardian',
            'description': 'Helped return 5 lost items on campus.',
            'icon': 'fa-shield-halved',
            'returns_threshold': 5,
            'points_threshold': 0,
        },
        {
            'slug': 'century-club',
            'name': 'Century Club',
            'description': 'Accumulated over 100 CampusCare citizenship points.',
            'icon': 'fa-trophy',
            'returns_threshold': 0,
            'points_threshold': 100,
        },
        {
            'slug': 'master-finder',
            'name': 'Master Finder',
            'description': 'Elite campus recovery contributor with 10+ successful returns.',
            'icon': 'fa-crown',
            'returns_threshold': 10,
            'points_threshold': 250,
        },
    ]

    @classmethod
    def get_reward_points_for_action(cls, action_type: str, default_points: int = 50) -> int:
        """Retrieves points configured in RewardRule or uses default."""
        from items.models import RewardRule
        rule = RewardRule.objects.filter(action_type=action_type, is_active=True).first()
        if rule:
            return rule.points
        return default_points

    @classmethod
    @transaction.atomic
    def award_handover_reward(cls, handover):
        """
        Awards reward points to the item returner/holder upon verified handover.
        Applies safeguards against self-claiming and duplicate reward transactions.
        """
        from items.models import Handover, RewardTransaction
        from items.services.notification_service import NotificationService

        if handover.status != Handover.STATUS_VERIFIED:
            raise ValueError("Reward can only be awarded for verified, completed handovers.")

        beneficiary = handover.held_by
        claimant = handover.claimant

        # Safeguard 1: Anti-self-claim fraud check
        if beneficiary == claimant:
            logger.warning(
                "Prevented reward award: claimant and holder are the same user (ID %s).",
                beneficiary.pk
            )
            return None, []

        # Safeguard 2: Idempotency check via unique transaction constraint
        existing = RewardTransaction.objects.filter(
            user=beneficiary,
            item=handover.item,
            transaction_type=RewardTransaction.TYPE_ITEM_RETURNED
        ).first()

        if existing:
            logger.info("Reward already awarded for item #%s to user %s.", handover.item_id, beneficiary.username)
            return existing, []

        # Get configurable points amount
        points = cls.get_reward_points_for_action('item_returned', default_points=50)

        # Create ledger transaction
        tx = RewardTransaction.objects.create(
            user=beneficiary,
            item=handover.item,
            handover=handover,
            points=points,
            transaction_type=RewardTransaction.TYPE_ITEM_RETURNED,
            description=f"Reward points for returning item '{handover.item.title}' via verified OTP handover."
        )

        # Update user total points
        beneficiary.reward_points = (beneficiary.reward_points or 0) + points
        beneficiary.save(update_fields=['reward_points'])

        # Evaluate achievement badges
        new_badges = cls.evaluate_badges(beneficiary)

        # Send in-app notification
        NotificationService.notify_reward_earned(
            user=beneficiary,
            points=points,
            reason=f"Safely returning '{handover.item.title}' to verified owner",
            badges=new_badges
        )

        return tx, new_badges

    @classmethod
    def ensure_default_badges(cls):
        """Creates standard milestone badges in database if they don't already exist."""
        from items.models import Badge
        for b_data in cls.DEFAULT_BADGES:
            Badge.objects.get_or_create(
                slug=b_data['slug'],
                defaults=b_data
            )

    @classmethod
    def evaluate_badges(cls, user):
        """
        Checks if user meets criteria for any new achievement badges
        and awards them.
        Returns list of newly awarded UserBadge instances.
        """
        from items.models import Badge, UserBadge, RewardTransaction

        cls.ensure_default_badges()

        completed_returns = RewardTransaction.objects.filter(
            user=user,
            transaction_type=RewardTransaction.TYPE_ITEM_RETURNED
        ).count()

        points = user.reward_points or 0
        already_earned_badge_ids = set(
            UserBadge.objects.filter(user=user).values_list('badge_id', flat=True)
        )

        newly_awarded = []
        for badge in Badge.objects.all():
            if badge.id in already_earned_badge_ids:
                continue

            returns_ok = completed_returns >= badge.returns_threshold
            points_ok = points >= badge.points_threshold

            if returns_ok and points_ok:
                ub = UserBadge.objects.create(user=user, badge=badge)
                newly_awarded.append(ub)

        return newly_awarded

    @classmethod
    def get_leaderboard(cls, institution=None, limit=20):
        """
        Returns ranked campus recovery citizenship leaderboard with
        privacy-conscious anonymized student display formats.
        """
        from django.contrib.auth import get_user_model
        from items.models import RewardTransaction

        User = get_user_model()
        qs = User.objects.filter(is_active=True, reward_points__gt=0)
        if institution:
            qs = qs.filter(institution=institution)

        users = qs.prefetch_related('badges__badge').order_by('-reward_points', 'date_joined')[:limit]

        leaderboard_entries = []
        for rank, u in enumerate(users, start=1):
            # Privacy-conscious display name: First Name + Last Initial (e.g. "Aarav S.")
            if u.first_name:
                last_init = f" {u.last_name[0]}." if u.last_name else ""
                masked_name = f"{u.first_name}{last_init}"
            else:
                masked_name = u.username[:3] + "***"

            dept_display = u.display_department

            # Count returns
            returns_count = RewardTransaction.objects.filter(
                user=u,
                transaction_type=RewardTransaction.TYPE_ITEM_RETURNED
            ).count()

            badges_list = [ub.badge for ub in u.badges.all()]

            leaderboard_entries.append({
                'rank': rank,
                'user_id': u.pk,
                'display_name': masked_name,
                'department': dept_display,
                'role': u.get_role_display(),
                'reward_points': u.reward_points,
                'returns_count': returns_count,
                'badges': badges_list,
            })

        return leaderboard_entries

