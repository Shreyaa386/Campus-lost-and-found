"""
Reward and Gamification Service for CampusCare.
Manages reward points ledger, duplicate transaction prevention,
academic duty leave (DL) milestone rewards, badges, and privacy-conscious campus leaderboards.
"""

import logging
from django.db import transaction
from django.utils.text import slugify

logger = logging.getLogger(__name__)


class RewardService:
    """
    Handles point calculation, ledger persistence, badge progression,
    academic Duty Leave (DL) milestone progression, and anti-fraud checks.
    """

    DEFAULT_BADGES = [
        {
            'slug': 'first-return',
            'name': 'Good Samaritan',
            'description': 'Safely returned your first found item on campus. Earned 2 DL.',
            'icon': 'fa-handshake',
            'returns_threshold': 1,
            'points_threshold': 0,
            'reward': '2 DL',
        },
        {
            'slug': 'campus-guardian',
            'name': 'Campus Guardian',
            'description': 'Helped return 5 lost items on campus. Earned 4 DL.',
            'icon': 'fa-shield-halved',
            'returns_threshold': 5,
            'points_threshold': 0,
            'reward': '4 DL',
        },
        {
            'slug': 'campus-legend',
            'name': 'Campus Legend',
            'description': 'Returned more than 5 items (6+ returns) on campus. Earned 1 Week DL.',
            'icon': 'fa-crown',
            'returns_threshold': 6,
            'points_threshold': 0,
            'reward': '1 Week DL',
        },
        {
            'slug': 'century-club',
            'name': 'Century Club',
            'description': 'Accumulated over 100 CampusCare citizenship points.',
            'icon': 'fa-trophy',
            'returns_threshold': 0,
            'points_threshold': 100,
            'reward': '',
        },
        {
            'slug': 'master-finder',
            'name': 'Master Finder',
            'description': 'Elite campus recovery contributor with 10+ successful returns.',
            'icon': 'fa-medal',
            'returns_threshold': 10,
            'points_threshold': 250,
            'reward': '',
        },
    ]

    DEFAULT_MILESTONES = [
        {
            'slug': 'first-return-2dl',
            'title': '2 DL',
            'returns_required': 1,
            'description': 'Awarded for safely returning your first found item on campus.',
            'badge_name': 'Good Samaritan',
            'icon': 'fa-handshake',
        },
        {
            'slug': 'five-returns-4dl',
            'title': '4 DL',
            'returns_required': 5,
            'description': 'Awarded upon reaching 5 successfully returned items on campus.',
            'badge_name': 'Campus Guardian',
            'icon': 'fa-shield-halved',
        },
        {
            'slug': 'six-returns-1week-dl',
            'title': '1 Week DL',
            'returns_required': 6,
            'description': 'Awarded for returning more than 5 items (6 or more) on campus.',
            'badge_name': 'Campus Legend',
            'icon': 'fa-crown',
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
    def ensure_default_badges(cls):
        """Creates standard milestone badges in database if they don't already exist."""
        from items.models import Badge
        for b_data in cls.DEFAULT_BADGES:
            Badge.objects.get_or_create(
                slug=b_data['slug'],
                defaults=b_data
            )

    @classmethod
    def ensure_default_milestones(cls):
        """Creates official academic duty leave (DL) milestones if not present."""
        from items.models import MilestoneReward
        for m_data in cls.DEFAULT_MILESTONES:
            MilestoneReward.objects.get_or_create(
                slug=m_data['slug'],
                defaults=m_data
            )

    @classmethod
    def get_user_successful_returns_count(cls, user):
        """
        Calculates the number of distinct items successfully returned by the user.
        Counts ONLY verified completed handovers or items marked as returned to rightful owners.
        Excludes lost items, pending/rejected claims, and unverified handovers.
        """
        from items.models import Handover, RewardTransaction, Item

        if not user or not user.is_authenticated:
            return 0

        # Verified handovers where user was custodian/holder (held_by)
        verified_handover_item_ids = set(
            Handover.objects.filter(
                held_by=user,
                status=Handover.STATUS_VERIFIED
            ).values_list('item_id', flat=True)
        )

        # Verified return ledger transactions
        tx_item_ids = set(
            RewardTransaction.objects.filter(
                user=user,
                transaction_type=RewardTransaction.TYPE_ITEM_RETURNED
            ).exclude(item__isnull=True).values_list('item_id', flat=True)
        )

        # Found items reported by user that reached STATUS_RETURNED
        found_item_ids = set(
            Item.objects.filter(
                user=user,
                report_type=Item.REPORT_TYPE_FOUND,
                status=Item.STATUS_RETURNED
            ).values_list('id', flat=True)
        )

        all_returned_items = verified_handover_item_ids | tx_item_ids | found_item_ids
        return len(all_returned_items)

    @classmethod
    def get_user_milestone_progress(cls, user):
        """
        Evaluates user's milestone progress and returns structured progress data
        for the dashboard and Rewards & Points pages.
        """
        from items.models import MilestoneReward, UserMilestoneReward

        cls.ensure_default_milestones()
        returns_count = cls.get_user_successful_returns_count(user)

        earned_records = {}
        if user and user.is_authenticated:
            for um in UserMilestoneReward.objects.filter(user=user).select_related('milestone'):
                earned_records[um.milestone.returns_required] = um

        milestones_list = []
        earned_dl_list = []
        next_milestone = None

        all_milestones = MilestoneReward.objects.filter(is_active=True).order_by('returns_required')
        for m in all_milestones:
            is_earned = (m.returns_required in earned_records) or (returns_count >= m.returns_required)
            um_record = earned_records.get(m.returns_required)

            if is_earned:
                earned_dl_list.append(m.title)
                progress_pct = 100
                progress_text = f"{m.returns_required}/{m.returns_required} Completed"
            else:
                progress_pct = min(100, int((returns_count / m.returns_required) * 100)) if m.returns_required else 0
                progress_text = f"{returns_count}/{m.returns_required} Returns"
                if next_milestone is None:
                    next_milestone = {
                        'milestone': m,
                        'remaining': max(0, m.returns_required - returns_count),
                        'progress_pct': progress_pct,
                    }

            milestones_list.append({
                'milestone': m,
                'is_earned': is_earned,
                'awarded_at': um_record.awarded_at if um_record else None,
                'progress_pct': progress_pct,
                'progress_text': progress_text,
            })

        # Overall progress percentage towards all milestones (max 6 returns)
        overall_pct = min(100, int((returns_count / 6) * 100))

        return {
            'returns_count': returns_count,
            'milestones': milestones_list,
            'earned_dl_list': earned_dl_list,
            'earned_dl_summary': " + ".join(earned_dl_list) if earned_dl_list else "0 DL",
            'next_milestone': next_milestone,
            'overall_progress_pct': overall_pct,
            'all_completed': (next_milestone is None),
        }

    @classmethod
    @transaction.atomic
    def evaluate_milestone_rewards(cls, user, handover=None, item=None):
        """
        Checks user's returned item count against milestone thresholds:
        - 1 item -> 2 DL
        - 5 items -> 4 DL
        - 6+ items (> 5 items) -> 1 Week DL
        Guarantees that each milestone is awarded only once (atomic idempotency).
        """
        from items.models import MilestoneReward, UserMilestoneReward, RewardTransaction
        from items.services.notification_service import NotificationService

        if not user or not user.is_authenticated:
            return []

        cls.ensure_default_milestones()
        cls.ensure_default_badges()

        returns_count = cls.get_user_successful_returns_count(user)
        already_awarded_m_ids = set(
            UserMilestoneReward.objects.filter(user=user).values_list('milestone_id', flat=True)
        )

        newly_awarded = []
        eligible_milestones = MilestoneReward.objects.filter(
            is_active=True,
            returns_required__lte=returns_count
        ).order_by('returns_required')

        ref_item = item or (handover.item if handover else None)

        for milestone in eligible_milestones:
            if milestone.id in already_awarded_m_ids:
                continue

            # Award milestone
            um = UserMilestoneReward.objects.create(
                user=user,
                milestone=milestone,
                handover=handover,
                item=ref_item
            )
            already_awarded_m_ids.add(milestone.id)
            newly_awarded.append(um)

            # Record in transaction ledger
            RewardTransaction.objects.get_or_create(
                user=user,
                item=ref_item,
                transaction_type=RewardTransaction.TYPE_MILESTONE_REWARD,
                defaults={
                    'handover': handover,
                    'points': 0,
                    'description': f"Milestone Unlocked: {milestone.title} ({milestone.description})",
                }
            )

            # Send in-app notification
            try:
                NotificationService.notify_milestone_unlocked(
                    user=user,
                    milestone=milestone,
                    returns_count=returns_count,
                    item=ref_item
                )
            except Exception as e:
                logger.warning("Could not dispatch milestone notification: %s", e)

        # Also evaluate and award corresponding badges
        cls.evaluate_badges(user)

        return newly_awarded

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

        tx = existing
        if not existing:
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

        # Evaluate milestone duty leave (DL) rewards (2 DL, 4 DL, 1 Week DL)
        cls.evaluate_milestone_rewards(beneficiary, handover=handover, item=handover.item)

        # Send in-app notification if newly awarded points
        if not existing:
            NotificationService.notify_reward_earned(
                user=beneficiary,
                points=tx.points,
                reason=f"Safely returning '{handover.item.title}' to verified owner",
                badges=new_badges
            )

        return tx, new_badges

    @classmethod
    def evaluate_badges(cls, user):
        """
        Checks if user meets criteria for any new achievement badges
        and awards them.
        Returns list of newly awarded UserBadge instances.
        """
        from items.models import Badge, UserBadge

        cls.ensure_default_badges()

        completed_returns = cls.get_user_successful_returns_count(user)
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
        Ranked primarily by successfully returned items, then points.
        """
        from django.contrib.auth import get_user_model
        from items.models import RewardTransaction, UserMilestoneReward

        cls.ensure_default_milestones()
        cls.ensure_default_badges()

        User = get_user_model()
        qs = User.objects.filter(is_active=True)
        if institution:
            qs = qs.filter(institution=institution)

        users = qs.prefetch_related(
            'badges__badge',
            'earned_milestones__milestone'
        )

        entries = []
        for u in users:
            returns_count = cls.get_user_successful_returns_count(u)
            points = u.reward_points or 0

            # Only include users who have at least 1 return or some citizenship points
            if returns_count == 0 and points == 0:
                continue

            # Privacy-conscious display name: First Name + Last Initial (e.g. "Aarav S.")
            if u.first_name:
                last_init = f" {u.last_name[0]}." if u.last_name else ""
                masked_name = f"{u.first_name}{last_init}"
            else:
                masked_name = u.username[:3] + "***"

            dept_display = u.display_department

            # Earned DL milestones
            earned_milestones = [
                um.milestone.title
                for um in u.earned_milestones.all().order_by('milestone__returns_required')
            ]
            # Fallback if UserMilestoneReward not yet created but threshold met
            if not earned_milestones:
                if returns_count >= 6:
                    earned_milestones = ['2 DL', '4 DL', '1 Week DL']
                elif returns_count >= 5:
                    earned_milestones = ['2 DL', '4 DL']
                elif returns_count >= 1:
                    earned_milestones = ['2 DL']

            highest_dl = earned_milestones[-1] if earned_milestones else None

            badges_list = [ub.badge for ub in u.badges.all()]

            entries.append({
                'user_id': u.pk,
                'display_name': masked_name,
                'department': dept_display,
                'role': u.get_role_display(),
                'reward_points': points,
                'returns_count': returns_count,
                'earned_dl_list': earned_milestones,
                'highest_dl': highest_dl,
                'badges': badges_list,
                'date_joined': u.date_joined,
            })

        # Sort primarily by successfully returned items, then points, then date_joined
        entries.sort(key=lambda x: (x['returns_count'], x['reward_points'], -x['date_joined'].timestamp()), reverse=True)

        leaderboard_entries = []
        for rank, entry in enumerate(entries[:limit], start=1):
            entry['rank'] = rank
            leaderboard_entries.append(entry)

        return leaderboard_entries
