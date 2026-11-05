from django.urls import path
from . import views

app_name = 'items'

urlpatterns = [
    # Core directories & reporting
    path('', views.home_view, name='home'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('my-reports/', views.my_reports_view, name='my_reports'),
    path('lost/', views.lost_items_view, name='lost_items'),
    path('found/', views.found_items_view, name='found_items'),
    path('report/<str:report_type>/', views.report_item_view, name='report_item'),
    path('<int:pk>/', views.item_detail_view, name='item_detail'),
    path('code/<str:item_code>/', views.item_detail_by_code_view, name='item_detail_by_code'),
    path('<int:pk>/edit/', views.item_edit_view, name='item_edit'),
    path('<int:pk>/delete/', views.item_delete_view, name='item_delete'),
    path('<int:pk>/status/', views.item_update_status_view, name='item_update_status'),

    # Smart Matching
    path('<int:pk>/matches/', views.item_matches_view, name='item_matches'),
    path('<int:pk>/matches/<int:match_pk>/dismiss/', views.item_dismiss_match_view, name='item_dismiss_match'),

    # Ownership Verification & Claims
    path('<int:pk>/claim/', views.item_claim_create_view, name='item_claim'),
    path('claims/', views.my_claims_list_view, name='my_claims'),
    path('claims/<int:pk>/', views.claim_detail_view, name='claim_detail'),
    path('claims/<int:pk>/withdraw/', views.claim_withdraw_view, name='claim_withdraw'),

    # Staff Moderation & Multiple Claimants Review
    path('admin/manage/', views.admin_manage_reports_view, name='admin_manage'),
    path('admin/claims/', views.admin_claims_list_view, name='admin_claims_list'),
    path('admin/claims/<int:pk>/review/', views.admin_claim_review_view, name='admin_claim_review'),

    # In-App Notifications
    path('notifications/', views.notifications_list_view, name='notifications'),
    path('notifications/preferences/', views.notification_preferences_view, name='notification_preferences'),

    # Recovery, Handover, and Receipts
    path('claims/<int:claim_pk>/handover/initiate/', views.handover_initiate_view, name='handover_initiate'),
    path('handover/<int:pk>/', views.handover_detail_view, name='handover_detail'),
    path('receipts/<int:pk>/', views.recovery_receipt_view, name='recovery_receipt'),
    path('recovery-history/', views.recovery_history_view, name='recovery_history'),
    path('<int:pk>/timeline/', views.recovery_timeline_view, name='recovery_timeline'),
    path('<int:pk>/tag/', views.item_tag_view, name='item_tag'),
    path('<int:pk>/qr/', views.qr_tag_view, name='qr_tag'),

    # Anonymous Communication
    path('<int:pk>/chat/', views.item_conversation_view, name='item_conversation'),
    path('conversations/<int:pk>/', views.conversation_detail_view, name='conversation_detail'),
    path('messages/<int:pk>/report-abuse/', views.message_report_abuse_view, name='message_report_abuse'),

    # Rewards & Leaderboard
    path('leaderboard/', views.leaderboard_view, name='leaderboard'),
    path('rewards/', views.leaderboard_view, name='rewards'),
]
