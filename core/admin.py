from django.contrib import admin
from .models import Institution, Department, CampusLocation, Category, AuditLog, SecurityAlert


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'domain', 'city', 'is_active', 'created_at')
    list_filter = ('is_active', 'city')
    search_fields = ('name', 'short_name', 'domain')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'institution', 'is_active')
    list_filter = ('institution', 'is_active')
    search_fields = ('name', 'code', 'institution__name')


@admin.register(CampusLocation)
class CampusLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'building', 'floor', 'latitude', 'longitude', 'institution', 'is_active')
    list_filter = ('institution', 'building', 'is_active')
    search_fields = ('name', 'building', 'description')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'institution', 'icon', 'is_active')
    list_filter = ('is_active', 'institution')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'actor', 'action', 'target_repr', 'ip_address')
    list_filter = ('action', 'timestamp')
    search_fields = ('actor__username', 'target_repr', 'ip_address')
    readonly_fields = ('actor', 'action', 'target_model', 'target_object_id', 'target_repr', 'institution', 'ip_address', 'user_agent', 'details', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    list_display = ('title', 'alert_type', 'severity', 'status', 'user', 'created_at')
    list_filter = ('alert_type', 'severity', 'status', 'created_at')
    search_fields = ('title', 'description', 'user__username')

