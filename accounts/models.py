"""Database models for authenticated users."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """User account with an application-specific role."""

    class UserType(models.TextChoices):
        """Supported user roles for the calibration application."""

        ADMIN = "admin", "Admin"
        TECHNICAL_MANAGER = "technical_manager", "Technical Manager"
        CALIBRATION_ENGINEER = (
            "calibration_engineer",
            "Calibration Engineer",
        )

    user_type = models.CharField(
        max_length=32,
        choices=UserType.choices,
        default=UserType.CALIBRATION_ENGINEER,
        db_index=True,
    )

    def __str__(self):
        """Return a readable label for the account."""
        return f"{self.username} ({self.user_type})"
