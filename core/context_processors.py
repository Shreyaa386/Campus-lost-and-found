"""
Context Processors for CampusCare Multi-Institution Branding & Tenant State.
Injects current institution branding, colors, logos, and subscription capabilities
into all template contexts.
"""

from core.models import Institution


def institution_context(request):
    """
    Exposes current tenant information and branding parameters to all templates.
    """
    institution = getattr(request, 'institution', None)

    if not institution and hasattr(request, 'user') and request.user.is_authenticated:
        institution = getattr(request.user, 'institution', None)

    primary_color = institution.primary_color if institution else "#1e3a8a"
    secondary_color = institution.secondary_color if institution else "#3b82f6"
    welcome_message = institution.welcome_message if institution else "Welcome to CampusCare Lost & Found"

    logo_url = ""
    if institution:
        if institution.logo:
            logo_url = institution.logo.url
        elif institution.logo_url:
            logo_url = institution.logo_url

    has_chatbot = institution.has_feature('ai_chatbot') if institution else True
    has_predictions = institution.has_feature('predictive_analytics') if institution else False

    # Fetch active institutions for cross-campus switcher
    all_institutions = Institution.objects.filter(is_active=True).only('id', 'name', 'short_name', 'slug')

    unread_notifications_count = 0
    sidebar_user_stats = {'reports_count': 0, 'claims_count': 0, 'reward_points': 0}
    if hasattr(request, 'user') and request.user.is_authenticated:
        try:
            unread_notifications_count = request.user.notifications.filter(is_read=False).count()
        except Exception:
            unread_notifications_count = 0
        try:
            sidebar_user_stats['reports_count'] = getattr(request.user, 'reported_items', None).count() if hasattr(request.user, 'reported_items') else 0
            sidebar_user_stats['claims_count'] = getattr(request.user, 'claims', None).count() if hasattr(request.user, 'claims') else 0
            if hasattr(request.user, 'gamification_profile'):
                sidebar_user_stats['reward_points'] = request.user.gamification_profile.total_points
        except Exception:
            pass

    return {
        'current_institution': institution,
        'institution_name': institution.name if institution else "Lovely Professional University (LPU), Phagwara, Punjab",
        'institution_short_name': (institution.short_name or institution.name) if institution else "LPU",
        'institution_primary_color': primary_color,
        'institution_secondary_color': secondary_color,
        'institution_logo_url': logo_url,
        'institution_welcome': welcome_message,
        'institution_has_chatbot': has_chatbot,
        'institution_has_predictions': has_predictions,
        'all_active_institutions': all_institutions,
        'unread_notifications_count': unread_notifications_count,
        'sidebar_user_stats': sidebar_user_stats,
    }

