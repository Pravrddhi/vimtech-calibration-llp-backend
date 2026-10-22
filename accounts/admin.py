"""Django Admin configuration for user accounts."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Expose the application role in the Django user admin."""

    fieldsets = UserAdmin.fieldsets + (
        ("Vimtech Calibration", {"fields": ("user_type",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Vimtech Calibration", {"fields": ("user_type",)}),
    )
    list_display = (
        "username",
        "email",
        "user_type",
        "is_active",
        "is_staff",
    )
    list_filter = ("user_type", "is_active", "is_staff")
