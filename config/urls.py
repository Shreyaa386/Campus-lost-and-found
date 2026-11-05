"""
URL configuration for config project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from accounts import views as account_views
from items import views as item_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Shortcut named URLs
    path('login/', account_views.login_view, name='login'),
    path('logout/', account_views.logout_view, name='logout'),
    path('register/', account_views.register_view, name='register'),
    path('signup/', account_views.register_view, name='signup'),
    path('profile/', account_views.profile_view, name='profile'),
    path('dashboard/', item_views.dashboard_view, name='dashboard'),
    path('home/', item_views.home_view, name='home'),

    # App URLs
    path('security-dashboard/', include('core.dashboard_urls')),
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('', include('items.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
