from django.urls import path
from . import views_chatbot, views_billing, views_erp

urlpatterns = [
    # AI Assistant
    path('assistant/', views_chatbot.assistant_view, name='assistant'),
    path('assistant/api/chat/', views_chatbot.api_assistant_chat, name='api_assistant_chat'),

    # Billing, Subscriptions & Payments
    path('billing/plans/', views_billing.subscription_plans_view, name='subscription_plans'),
    path('billing/checkout/<str:plan_code>/', views_billing.initiate_checkout_view, name='initiate_checkout'),
    path('billing/webhooks/gateway/', views_billing.payment_webhook_view, name='payment_webhook'),

    # ERP Synchronization API
    path('api/v1/erp/sync/', views_erp.erp_sync_api_view, name='erp_sync_api'),
]

