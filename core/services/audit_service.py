"""
Audit Logging Service for CampusCare.
Provides centralized, tamper-resistant tracking of administrative actions,
claim decisions, item status modifications, account role/status changes, and exports.
Guarantees zero storage of sensitive credentials, passwords, OTPs, or verification secrets.
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class AuditService:
    """
    Handles generation of immutable audit trail records across campus administrative operations.
    """

    @classmethod
    def get_client_ip(cls, request):
        """Extracts client IP address safely from request headers."""
        if not request:
            return None
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    @classmethod
    def get_user_agent(cls, request):
        if not request:
            return ""
        return request.META.get('HTTP_USER_AGENT', '')[:250]

    @classmethod
    def log_action(cls, action: str, actor=None, target_obj=None, institution=None, details: dict = None, request=None):
        """
        Records an administrative action into the immutable AuditLog ledger.
        """
        from core.models import AuditLog

        try:
            if actor is None and request and hasattr(request, 'user') and request.user.is_authenticated:
                actor = request.user

            target_model = ""
            target_object_id = ""
            target_repr = ""

            if target_obj is not None:
                target_model = target_obj.__class__.__name__
                target_object_id = str(getattr(target_obj, 'pk', ''))
                target_repr = str(target_obj)[:190]
                if not institution and hasattr(target_obj, 'institution'):
                    institution = getattr(target_obj, 'institution')

            if not institution and actor and hasattr(actor, 'institution'):
                institution = actor.institution

            ip_address = cls.get_client_ip(request)
            user_agent = cls.get_user_agent(request)

            clean_details = dict(details) if isinstance(details, dict) else {}

            log_entry = AuditLog.objects.create(
                actor=actor,
                action=action,
                target_model=target_model,
                target_object_id=target_object_id,
                target_repr=target_repr,
                institution=institution,
                ip_address=ip_address,
                user_agent=user_agent,
                details=clean_details
            )
            return log_entry
        except Exception as e:
            logger.error("Failed to write audit log entry for action '%s': %s", action, e, exc_info=True)
            return None

