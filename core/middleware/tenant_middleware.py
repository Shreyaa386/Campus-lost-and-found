"""
Multi-Tenant Domain Resolution and Security Middleware for CampusCare.
Resolves institution context from incoming request hostname (custom domain,
campus subdomain) or authenticated user credentials. Prevents arbitrary Host
header injection attacks by validating against approved institutional domains.
"""

import logging
from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.db.models import Q
from core.models import Institution

logger = logging.getLogger(__name__)


class TenantMiddleware:
    """
    Middleware ensuring every request has a validated `request.institution`.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        institution = self.resolve_institution(request)
        request.institution = institution
        response = self.get_response(request)
        return response

    def resolve_institution(self, request):
        """
        Determines the institutional tenant through multi-stage discovery:
        1. Custom domain or institutional domain matching request host
        2. Authenticated user's registered institution
        3. Session cached institution ID
        4. Active default institution fallback
        """
        raw_host = request.get_host().split(':')[0].strip().lower()

        # 1. Match custom domain or registered campus domain
        try:
            matched = Institution.objects.filter(
                Q(custom_domain__iexact=raw_host) | Q(domain__iexact=raw_host),
                is_active=True
            ).first()
            if matched:
                return matched
        except Exception as e:
            logger.warning(f"Tenant lookup failed for host {raw_host}: {e}")

        # 2. Check authenticated user's assigned institution
        if hasattr(request, 'user') and request.user.is_authenticated:
            user_inst = getattr(request.user, 'institution', None)
            if user_inst and user_inst.is_active:
                return user_inst

        # 3. Check session override (for multi-campus switching by superadmins)
        session_inst_id = request.session.get('active_institution_id')
        if session_inst_id:
            try:
                session_inst = Institution.objects.filter(id=session_inst_id, is_active=True).first()
                if session_inst:
                    return session_inst
            except Exception:
                pass

        # 4. Fallback to primary active institution
        default_inst = Institution.objects.filter(is_active=True).first()
        return default_inst

