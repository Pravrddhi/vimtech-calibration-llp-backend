"""Permission classes for account-management APIs."""

from rest_framework.permissions import BasePermission


class IsApplicationAdmin(BasePermission):
    """Require an active staff user with the application admin role."""

    message = "Active application admin and staff privileges are required."

    def has_permission(self, request, view):
        """Check both the application role and Django staff status."""
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.is_staff
            and user.user_type == user.UserType.ADMIN
        )