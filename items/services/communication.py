"""
Anonymous Communication Service for CampusCare.
Allows authorized claimants, finders, and staff to coordinate recovery
without publicly leaking personal phone numbers or email addresses.
Includes abuse reporting and strict permission enforcement.
"""

import logging
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.urls import reverse

logger = logging.getLogger(__name__)


class CommunicationService:
    """
    Coordinates anonymous conversations and enforces participant isolation.
    """

    @classmethod
    def get_or_create_conversation(cls, item, user1, user2, claim=None):
        """
        Finds or initializes a private conversation thread between two campus users
        regarding a specific item.
        """
        from items.models import ItemConversation

        if user1 == user2:
            raise ValidationError("Cannot establish a conversation thread with yourself.")

        conv = ItemConversation.objects.filter(
            Q(item=item, participant_1=user1, participant_2=user2) |
            Q(item=item, participant_1=user2, participant_2=user1)
        ).first()

        if not conv:
            conv = ItemConversation.objects.create(
                item=item,
                claim=claim,
                participant_1=user1,
                participant_2=user2
            )

        return conv

    @classmethod
    def can_access(cls, conversation, user) -> bool:
        """Enforces that only conversation participants or staff can read/write."""
        if not user or not user.is_authenticated:
            return False
        if user in [conversation.participant_1, conversation.participant_2]:
            return True
        return getattr(user, 'is_staff_member', False)

    @classmethod
    def send_message(cls, conversation, sender, message_text: str):
        """
        Sends an anonymous message within a conversation.
        Dispatches private in-app notification to the counterpart without revealing
        email or phone number.
        """
        from items.models import ConversationMessage, Notification

        if not cls.can_access(conversation, sender):
            raise PermissionDenied("You are not authorized to send messages in this conversation.")

        clean_text = message_text.strip()
        if not clean_text:
            raise ValidationError("Message body cannot be empty.")

        msg = ConversationMessage.objects.create(
            conversation=conversation,
            sender=sender,
            message_text=clean_text
        )

        conversation.save(update_fields=['updated_at'])

        # Notify the recipient
        counterpart = (
            conversation.participant_2
            if sender == conversation.participant_1
            else conversation.participant_1
        )

        Notification.objects.create(
            recipient=counterpart,
            title=f"New Message: {conversation.item.title}",
            message=f"You received a new secure coordination message regarding '{conversation.item.title}'.",
            notification_type=Notification.TYPE_SYSTEM,
            link=reverse('items:conversation_detail', kwargs={'pk': conversation.pk})
        )

        return msg

    @classmethod
    def report_abuse(cls, message, reporting_user, reason: str):
        """
        Flags a message for campus staff review if inappropriate or abusive.
        """
        from items.models import Notification
        from django.contrib.auth import get_user_model

        if not cls.can_access(message.conversation, reporting_user):
            raise PermissionDenied("You do not have permission to report this message.")

        message.is_flagged_for_abuse = True
        message.flagged_by = reporting_user
        message.abuse_reason = reason.strip() or "Reported as inappropriate/abusive."
        message.save(update_fields=['is_flagged_for_abuse', 'flagged_by', 'abuse_reason'])

        # Notify staff/admin users
        User = get_user_model()
        staff_users = User.objects.filter(role__in=['staff', 'admin'], is_active=True)[:5]
        for staff in staff_users:
            Notification.objects.create(
                recipient=staff,
                title="Abuse Report Flagged",
                message=f"A message on item '{message.conversation.item.title}' was flagged for: {message.abuse_reason}",
                notification_type=Notification.TYPE_SYSTEM,
                link=reverse('items:conversation_detail', kwargs={'pk': message.conversation.pk})
            )

        return message

    @classmethod
    def get_masked_label(cls, message_sender, item, claimant=None) -> str:
        """
        Returns a privacy-safe label for the message sender.
        E.g. 'Finder / Reporter', 'Claimant', 'Campus Staff'.
        Never leaks real email, phone, or raw identifier.
        """
        if getattr(message_sender, 'is_staff_member', False):
            return "Campus Lost & Found Desk (Staff)"
        if item.user == message_sender:
            return "Item Reporter / Finder"
        if claimant and claimant == message_sender:
            return "Verified Claimant"
        return "Campus Student"

