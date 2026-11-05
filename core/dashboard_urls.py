from django.urls import path
from . import views_admin, views_billing

app_name = 'security_dashboard'

urlpatterns = [
    # Overview
    path('', views_admin.dashboard_overview_view, name='overview'),

    # User Governance
    path('users/', views_admin.user_list_view, name='users'),
    path('users/<int:user_id>/', views_admin.user_detail_view, name='user_detail'),
    path('users/<int:user_id>/toggle-status/', views_admin.user_toggle_status_view, name='user_toggle_status'),
    path('users/<int:user_id>/toggle-status/', views_admin.user_toggle_status_view, name='user_status_toggle'),
    path('users/<int:user_id>/update-role/', views_admin.user_update_role_view, name='user_update_role'),
    path('users/<int:user_id>/update-role/', views_admin.user_update_role_view, name='user_role_update'),

    # Item Governance & Archival
    path('items/', views_admin.item_management_list_view, name='items'),
    path('items/<int:item_id>/archive/', views_admin.item_archive_view, name='item_archive'),
    path('categories/', views_admin.category_management_view, name='categories'),
    path('locations/', views_admin.location_management_view, name='locations'),

    # Claim Moderation
    path('claims/', views_admin.claims_moderation_list_view, name='claims'),
    path('claims/<int:claim_id>/', views_admin.claim_moderation_decision_view, name='claim_detail'),

    # Security Monitoring
    path('security-alerts/', views_admin.security_alerts_view, name='security_alerts'),
    path('security-alerts/<int:alert_id>/review/', views_admin.security_alert_action_view, name='security_alert_action'),

    # Audit Logs
    path('audit-logs/', views_admin.audit_logs_view, name='audit_logs'),

    # Analytics & Intelligence
    path('analytics/', views_admin.analytics_view, name='analytics'),
    path('predictions/', views_admin.trend_predictions_view, name='predictions'),
    path('institution-analytics/', views_billing.multi_institution_analytics_view, name='institution_analytics'),

    # Geographic Heatmap
    path('heatmap/', views_admin.campus_heatmap_view, name='heatmap'),

    # Downloadable Reports (Excel & PDF)
    path('exports/', views_admin.export_reports_view, name='exports'),
]

