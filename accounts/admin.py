from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username', 'email', 'role', 'student_id',
        'display_department', 'reward_points', 'is_staff', 'is_active'
    )
    list_filter = ('role', 'is_staff', 'is_active', 'institution', 'department')
    search_fields = ('username', 'email', 'student_id', 'first_name', 'last_name')
    ordering = ('username',)

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Campus Information', {
            'fields': (
                'role', 'student_id', 'phone_number',
                'institution', 'department', 'department_name',
                'profile_picture', 'reward_points'
            )
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Campus Information', {
            'fields': (
                'role', 'email', 'student_id', 'phone_number',
                'institution', 'department', 'department_name',
                'profile_picture'
            )
        }),
    )
