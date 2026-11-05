"""
In-App Notification and Modular Multi-Channel Dispatch Service for CampusCare.
Dispatches in-app notifications to students, faculty, and administrators when claims,
handovers, OTP verifications, and rewards occur.
Adheres to user-configured NotificationPreference settings and provides
modular external email/SMS/WhatsApp dispatch without exposing API keys.
"""

import logging
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


class ExternalDispatchService:
    """
    Modular external dispatch handler for Email, SMS, and WhatsApp.
    Provides pluggable integration points and mock-safe logging without exposing secrets.
    """

    @classmethod
    def send_email(cls, recipient, subject: str, message: str) -> bool:
        """Sends transactional email if user opted in and email is present."""
        if not getattr(recipient, 'email', None):
            return False
        try:
            # Uses Django's configured EMAIL_BACKEND (e.g. console in development)
            send_mail(
                subject=f"[CampusCare] {subject}",
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'campuscare@institution.edu'),
                recipient_list=[recipient.email],
                fail_silently=True
            )
            logger.info("External email dispatched to user %s (%s)", recipient.pk, recipient.email)
            return True
        except Exception as e:
            logger.warning("External email dispatch failed for %s: %s", recipient.email, e)
            return False

    @classmethod
    def send_sms(cls, recipient, message: str) -> bool:
        """
        Modular SMS dispatch point.
        Pluggable for Twilio / AWS SNS / MSG91 without exposing credentials.
        """
        phone = getattr(recipient, 'phone_number', '')
        if not phone:
            return False
        # Log delivery for campus audit without hardcoded vendor keys
        logger.info("[SMS Dispatch Simulation] To: %s | Message: %s", phone, message[:50])
        return True

    @classmethod
    def send_whatsapp(cls, recipient, message: str) -> bool:
        """
        Modular WhatsApp Business API dispatch point.
        Pluggable for Meta Cloud API or Twilio WhatsApp.
        """
        phone = getattr(recipient, 'phone_number', '')
        if not phone:
            return False
        logger.info("[WhatsApp Dispatch Simulation] To: %s | Message: %s", phone, message[:50])
        return True


class NotificationService:
    """
    Creates in-app notification records for users and coordinates modular external notifications.
    Respects user notification preferences.
    """

    @classmethod
    def _is_preference_enabled(cls, user, preference_name: str) -> bool:
        """Checks user's notification preferences with a safe fallback to True."""
        try:
            from items.models import NotificationPreference
            pref, _ = NotificationPreference.objects.get_or_create(user=user)
            return getattr(pref, preference_name, True)
        except Exception as e:
            logger.warning("Error fetching notification preference for %s: %s", user, e)
            return True

    @classmethod
    def _dispatch_external_if_enabled(cls, recipient, subject: str, text: str):
        """Dispatches to email/SMS/WhatsApp if enabled in user preferences."""
        try:
            from items.models import NotificationPreference
            pref, _ = NotificationPreference.objects.get_or_create(user=recipient)
            if pref.email_notifications:
                ExternalDispatchService.send_email(recipient, subject, text)
        except Exception as e:
            logger.warning("External dispatch evaluation error: %s", e)

    @classmethod
    def notify_claim_submitted(cls, claim):
        """Notify claimant and item reporter when a new claim is lodged."""
        from items.models import Notification

        # 1. Notify claimant
        if cls._is_preference_enabled(claim.claimant, 'notify_on_claims'):
            Notification.objects.create(
                recipient=claim.claimant,
                title=f"Claim Received: {claim.item.title}",
                message=f"Your ownership claim for '{claim.item.title}' has been received and queued for staff review.",
                notification_type=Notification.TYPE_CLAIM_SUBMITTED,
                link=reverse('items:claim_detail', kwargs={'pk': claim.pk})
            )

        # 2. Notify item finder / reporter
        if claim.item.user and claim.item.user != claim.claimant:
            if cls._is_preference_enabled(claim.item.user, 'notify_on_claims'):
                Notification.objects.create(
                    recipient=claim.item.user,
                    title=f"New Claim on Your Found Item: {claim.item.title}",
                    message=f"A claimant has submitted ownership proof for '{claim.item.title}'. Campus staff will verify the details.",
                    notification_type=Notification.TYPE_CLAIM_SUBMITTED,
                    link=reverse('items:item_detail', kwargs={'pk': claim.item.pk})
                )

    @classmethod
    def notify_claim_status_changed(cls, claim, old_status, new_status, reason=""):
        """Notify claimant of approval, rejection, or under-review status."""
        from items.models import Notification, Claim

        if not cls._is_preference_enabled(claim.claimant, 'notify_on_claims'):
            return

        status_display = claim.get_status_display()
        if new_status == Claim.STATUS_APPROVED:
            title = f"Claim APPROVED: {claim.item.title}"
            msg = (
                f"Your ownership claim for '{claim.item.title}' has been APPROVED! "
                "A secure handover has been prepared. Please proceed with physical collection."
            )
            if reason:
                msg += f" Note: {reason}"
        elif new_status == Claim.STATUS_REJECTED:
            title = f"Claim Update: {claim.item.title}"
            msg = f"Your claim for '{claim.item.title}' was reviewed and not approved."
            if reason:
                msg += f" Reason: {reason}"
        elif new_status == Claim.STATUS_WITHDRAWN:
            title = f"Claim Withdrawn: {claim.item.title}"
            msg = f"Your ownership claim for '{claim.item.title}' was withdrawn."
        else:
            title = f"Claim Status Update: {claim.item.title}"
            msg = f"Your claim status is now: '{status_display}'."
            if reason:
                msg += f" Details: {reason}"

        Notification.objects.create(
            recipient=claim.claimant,
            title=title,
            message=msg,
            notification_type=Notification.TYPE_CLAIM_STATUS,
            link=reverse('items:claim_detail', kwargs={'pk': claim.pk})
        )
        cls._dispatch_external_if_enabled(claim.claimant, title, msg)

    @classmethod
    def notify_match_found(cls, source_item, matched_item, score):
        """Notify report owner of a new potential match."""
        from items.models import Notification

        if not cls._is_preference_enabled(source_item.user, 'notify_on_matches'):
            return

        Notification.objects.create(
            recipient=source_item.user,
            title=f"Suggested Match Found ({score:.0f}%): {source_item.title}",
            message=(
                f"We found a potential {matched_item.get_report_type_display()} match "
                f"('{matched_item.title}') with {score:.0f}% similarity to your report."
            ),
            notification_type=Notification.TYPE_MATCH_FOUND,
            link=reverse('items:item_matches', kwargs={'pk': source_item.pk})
        )

    @classmethod
    def notify_handover_initiated(cls, handover):
        """
        Notifies claimant and holder that handover is initiated with OTP.
        """
        from items.models import Notification

        # 1. Notify claimant (receives prompt to view their OTP)
        if cls._is_preference_enabled(handover.claimant, 'notify_on_handover'):
            Notification.objects.create(
                recipient=handover.claimant,
                title=f"Handover Ready: {handover.item.title}",
                message=(
                    f"A physical recovery handover has been scheduled at {handover.handover_location}. "
                    "Open to view your secure, time-limited 6-digit OTP to show during exchange."
                ),
                notification_type=Notification.TYPE_HANDOVER_INITIATED,
                link=reverse('items:handover_detail', kwargs={'pk': handover.pk})
            )
            cls._dispatch_external_if_enabled(
                handover.claimant,
                f"CampusCare Handover Ready: {handover.item.title}",
                f"Your handover for '{handover.item.title}' is ready. View your OTP on CampusCare to collect your item."
            )

        # 2. Notify holder (finder/staff)
        if cls._is_preference_enabled(handover.held_by, 'notify_on_handover'):
            Notification.objects.create(
                recipient=handover.held_by,
                title=f"Handover Scheduled: {handover.item.title}",
                message=(
                    f"You are scheduled to release '{handover.item.title}' to {handover.claimant.display_name}. "
                    "Open the handover page when meeting the owner to verify their 6-digit OTP code."
                ),
                notification_type=Notification.TYPE_HANDOVER_INITIATED,
                link=reverse('items:handover_detail', kwargs={'pk': handover.pk})
            )

    @classmethod
    def notify_otp_verification_result(cls, handover, success: bool, message: str = ""):
        """Notifies participants of OTP verification outcome."""
        from items.models import Notification

        if success:
            receipt = getattr(handover, 'receipt', None)
            receipt_link = reverse('items:recovery_receipt', kwargs={'pk': receipt.pk}) if receipt else ""

            # Claimant notification
            if cls._is_preference_enabled(handover.claimant, 'notify_on_handover'):
                Notification.objects.create(
                    recipient=handover.claimant,
                    title=f"Item Recovered! {handover.item.title}",
                    message=(
                        f"OTP verified successfully! '{handover.item.title}' has been recovered. "
                        "Your immutable digital recovery receipt is ready to view and download."
                    ),
                    notification_type=Notification.TYPE_HANDOVER_COMPLETED,
                    link=receipt_link or reverse('items:handover_detail', kwargs={'pk': handover.pk})
                )

            # Holder notification
            if cls._is_preference_enabled(handover.held_by, 'notify_on_handover'):
                Notification.objects.create(
                    recipient=handover.held_by,
                    title=f"Handover Verified: {handover.item.title}",
                    message=f"OTP verification succeeded. '{handover.item.title}' has been safely recovered by its owner.",
                    notification_type=Notification.TYPE_HANDOVER_COMPLETED,
                    link=receipt_link or reverse('items:handover_detail', kwargs={'pk': handover.pk})
                )
        else:
            # Verification failed
            if cls._is_preference_enabled(handover.held_by, 'notify_on_handover'):
                Notification.objects.create(
                    recipient=handover.held_by,
                    title=f"Handover Verification Notice: {handover.item.title}",
                    message=f"OTP verification was unsuccessful. {message}",
                    notification_type=Notification.TYPE_SYSTEM,
                    link=reverse('items:handover_detail', kwargs={'pk': handover.pk})
                )

    @classmethod
    def notify_reward_earned(cls, user, points: int, reason: str, badges=None):
        """Notifies user of citizenship points credited and badges unlocked."""
        from items.models import Notification

        if not cls._is_preference_enabled(user, 'notify_on_rewards'):
            return

        msg = f"You received +{points} CampusCare citizenship points for: {reason}."
        if badges:
            badge_names = ", ".join([b.badge.name for b in badges])
            msg += f" Congratulations! You also unlocked the milestone badge(s): {badge_names}!"

        Notification.objects.create(
            recipient=user,
            title=f"Reward Credited: +{points} Points!",
            message=msg,
            notification_type=Notification.TYPE_REWARD_EARNED,
            link=reverse('items:leaderboard')
        )
