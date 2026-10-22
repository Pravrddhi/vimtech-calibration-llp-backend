"""Tests for account authentication and profile API behavior."""

import json
import logging
import tempfile
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from config.logging_handlers import DailyFileHandler


User = get_user_model()


class DailyFileHandlerTests(SimpleTestCase):
    """Verify application log records are written to dated files."""

    def test_handler_writes_records_to_date_named_file(self):
        """Write formatted application events to the current day's file."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "config.logging_handlers.LOG_DIRECTORY",
                Path(temporary_directory),
            ):
                handler = DailyFileHandler()
                handler.setFormatter(logging.Formatter("%(message)s"))
                record = logging.LogRecord(
                    name="accounts.views",
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=1,
                    msg="authentication_succeeded user_id=%s",
                    args=(123,),
                    exc_info=None,
                )

                handler.emit(record)

                log_date = timezone.localtime(
                    datetime.fromtimestamp(
                        record.created,
                        tz=datetime_timezone.utc,
                    )
                ).strftime("%Y-%m-%d")
                log_path = (
                    Path(temporary_directory) / f"app-{log_date}.log"
                )
                log_content = log_path.read_text(encoding="utf-8")
                handler.close()

        self.assertIn("authentication_succeeded user_id=123", log_content)


class AuthenticationAPITests(APITestCase):
    """Verify login, JWT-protected profile access, and role safety."""

    def setUp(self):
        """Create engineer and admin accounts for API tests."""
        self.password = "safe-test-password-123"
        self.user = User.objects.create_user(
            username="engineer01",
            password=self.password,
            user_type=User.UserType.CALIBRATION_ENGINEER,
        )
        self.admin = User.objects.create_user(
            username="admin01",
            password="safe-admin-password-123",
            user_type=User.UserType.ADMIN,
            is_staff=True,
        )

    def test_login_returns_tokens_and_user_type(self):
        """Successful login returns both tokens and the database role."""
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(
            response.data["user"]["user_type"],
            User.UserType.CALIBRATION_ENGINEER,
        )

    def test_login_logs_success_without_tokens_or_password(self):
        """Log successful authentication without recording credentials."""
        with self.assertLogs("accounts.views", level="INFO") as captured:
            response = self.client.post(
                reverse("login"),
                {"username": self.user.username, "password": self.password},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log_output = "\n".join(captured.output)
        self.assertIn(f"user_id={self.user.pk}", log_output)
        self.assertNotIn(self.password, log_output)
        self.assertNotIn(response.data["access"], log_output)

    def test_login_rejects_invalid_credentials(self):
        """Reject invalid credentials without exposing account status."""
        with self.assertLogs("accounts.views", level="WARNING") as captured:
            response = self.client.post(
                reverse("login"),
                {"username": self.user.username, "password": "incorrect"},
                format="json",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertIn("authentication_failed", captured.output[0])

    def test_public_registration_is_not_available(self):
        """Reject unauthenticated attempts to create user accounts."""
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "new-engineer",
                "password": "Distinct-safe-Pass123!",
                "user_type": User.UserType.CALIBRATION_ENGINEER,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(User.objects.filter(username="new-engineer").exists())

    def test_admin_can_create_a_non_admin_user_without_tokens(self):
        """Create accounts with safe privilege flags and no issued tokens."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "new-engineer",
                "password": "Distinct-safe-Pass123!",
                "first_name": "New",
                "last_name": "Engineer",
                "email": "engineer@example.com",
                "user_type": User.UserType.CALIBRATION_ENGINEER,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_user = User.objects.get(username="new-engineer")
        self.assertTrue(
            created_user.check_password("Distinct-safe-Pass123!")
        )
        self.assertEqual(
            created_user.user_type,
            User.UserType.CALIBRATION_ENGINEER,
        )
        self.assertFalse(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

    def test_admin_can_check_username_availability(self):
        """Report whether a username is already present in the database."""
        self.client.force_authenticate(user=self.admin)

        available_response = self.client.get(
            reverse("check-username"),
            {"username": "available-user"},
        )
        taken_response = self.client.get(
            reverse("check-username"),
            {"username": self.user.username},
        )

        self.assertEqual(available_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            available_response.data,
            {"username": "available-user", "available": True},
        )
        self.assertEqual(taken_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            taken_response.data,
            {"username": self.user.username, "available": False},
        )

    def test_non_admin_cannot_check_username_availability(self):
        """Keep username lookup restricted to authorized administrators."""
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            reverse("check-username"),
            {"username": "available-user"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_username_availability_requires_a_username(self):
        """Reject availability checks that omit the username."""
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(reverse("check-username"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_cannot_create_user(self):
        """An engineer cannot create users through the admin API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "attempted-user",
                "password": "Distinct-safe-Pass123!",
                "user_type": User.UserType.TECHNICAL_MANAGER,
            },
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertFalse(
            User.objects.filter(username="attempted-user").exists()
        )

    def test_admin_cannot_create_another_admin_without_superuser_flag(self):
        """Restrict admin role creation to trusted Django superusers."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "attempted-admin",
                "password": "Distinct-safe-Pass123!",
                "user_type": User.UserType.ADMIN,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertFalse(
            User.objects.filter(username="attempted-admin").exists()
        )

    def test_superuser_can_create_admin_without_superuser_status(self):
        """Create application admins without propagating Django superuser."""
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_superuser"])
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "new-admin",
                "password": "Distinct-safe-Pass123!",
                "user_type": User.UserType.ADMIN,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_user = User.objects.get(username="new-admin")
        self.assertTrue(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)

    def test_inactive_admin_cannot_create_users(self):
        """Reject inactive accounts even when their role flags are elevated."""
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("user-create"),
            {
                "username": "inactive-admin-created",
                "password": "Distinct-safe-Pass123!",
                "user_type": User.UserType.TECHNICAL_MANAGER,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            User.objects.filter(username="inactive-admin-created").exists()
        )

    def test_admin_creation_rejects_weak_password(self):
        """Apply configured Django password validators to new accounts."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "weak-password-user",
                "password": "short",
                "user_type": User.UserType.CALIBRATION_ENGINEER,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("password", response.data)
        self.assertFalse(
            User.objects.filter(username="weak-password-user").exists()
        )

    def test_admin_creation_rejects_privileged_fields(self):
        """Ignore client attempts to set staff or superuser flags."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "forged-staff",
                "password": "Distinct-safe-Pass123!",
                "user_type": User.UserType.CALIBRATION_ENGINEER,
                "is_staff": True,
                "is_superuser": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_user = User.objects.get(username="forged-staff")
        self.assertFalse(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)

    def test_profile_requires_authentication(self):
        """Anonymous callers cannot access the current-user profile."""
        response = self.client.get(reverse("userdetails"))

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_profile_returns_authenticated_user(self):
        """A valid access token grants access to only the caller's profile."""
        login_response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}"
        )

        response = self.client.get(reverse("userdetails"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], self.user.username)
        self.assertEqual(response.data["is_staff"], self.user.is_staff)
        self.assertEqual(response.data["is_active"], self.user.is_active)
        self.assertEqual(
            response.data["user_type"],
            User.UserType.CALIBRATION_ENGINEER,
        )
        self.assertNotIn("password", response.data)

    def test_profile_role_is_read_only(self):
        """Profile serialization never accepts a role promotion."""
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            reverse("userdetails"),
            {"user_type": User.UserType.ADMIN},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.user_type,
            User.UserType.CALIBRATION_ENGINEER,
        )

    def test_password_change_updates_password_and_revokes_refresh_tokens(self):
        """Update own password and blacklist outstanding refresh tokens."""
        refresh = RefreshToken.for_user(self.user)
        refresh_token = str(refresh)
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("change-password"),
            {
                "current_password": self.password,
                "new_password": "Brand-new-safe-password-456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.data)
        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password("Brand-new-safe-password-456!")
        )
        refresh_response = self.client.post(
            reverse("token_refresh"),
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(
            refresh_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_password_change_rejects_incorrect_current_password(self):
        """Do not change passwords unless the current one is verified."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("change-password"),
            {
                "current_password": "wrong-current-password",
                "new_password": "Brand-new-safe-password-456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    def test_password_change_rejects_weak_or_reused_password(self):
        """Enforce strength and prevent reusing the current password."""
        self.client.force_authenticate(user=self.user)
        weak_response = self.client.post(
            reverse("change-password"),
            {
                "current_password": self.password,
                "new_password": "short",
            },
            format="json",
        )
        reused_response = self.client.post(
            reverse("change-password"),
            {
                "current_password": self.password,
                "new_password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            weak_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            reused_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    def test_password_change_requires_authentication(self):
        """Reject password changes without a valid access token."""
        response = self.client.post(
            reverse("change-password"),
            {
                "current_password": self.password,
                "new_password": "Brand-new-safe-password-456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_openapi_schema_is_public_and_includes_auth_endpoints(self):
        """The public schema documents the authentication API routes."""
        response = self.client.get(reverse("schema"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("/api/login/", response.data["paths"])
        self.assertIn("/api/users/", response.data["paths"])
        self.assertIn("/api/userdetails/", response.data["paths"])
        self.assertIn(
            "/api/userdetails/change-password/",
            response.data["paths"],
        )
        self.assertNotIn("/api/register/", response.data["paths"])

    def test_swagger_ui_is_public(self):
        """Swagger UI can be opened without an access token."""
        response = self.client.get(reverse("swagger-ui"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(DEBUG=True)
    def test_api_request_logs_metadata_without_sensitive_values(self):
        """Log API metadata without recording passwords, tokens, or queries."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "config.middleware.LOG_DIRECTORY",
                Path(temporary_directory),
            ):
                response = self.client.post(
                    f"{reverse('login')}?token=query-secret",
                    {
                        "username": self.user.username,
                        "password": self.password,
                    },
                    format="json",
                )

            log_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
            log_path = Path(temporary_directory) / f"api-{log_date}.log"
            record = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(record["method"], "POST")
        self.assertEqual(record["path"], reverse("login"))
        self.assertIsNone(record["user_id"])
        self.assertEqual(record["status_code"], status.HTTP_200_OK)
        self.assertNotIn(self.password, json.dumps(record))
        self.assertNotIn(response.data["access"], json.dumps(record))
        self.assertNotIn("query-secret", json.dumps(record))

    @override_settings(DEBUG=True)
    def test_api_request_log_includes_authenticated_user_id(self):
        """Include the authenticated account ID in request metadata."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "config.middleware.LOG_DIRECTORY",
                Path(temporary_directory),
            ):
                self.client.force_authenticate(user=self.user)
                response = self.client.get(reverse("userdetails"))

            log_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
            log_path = Path(temporary_directory) / f"api-{log_date}.log"
            record = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(record["user_id"], self.user.pk)

    @override_settings(DEBUG=True)
    def test_non_200_api_response_is_written_to_application_log(self):
        """Record non-200 API statuses in the dated application log."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "config.logging_handlers.LOG_DIRECTORY",
                Path(temporary_directory),
            ):
                response = self.client.get(reverse("userdetails"))

            log_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
            log_path = Path(temporary_directory) / f"app-{log_date}.log"
            log_content = log_path.read_text(encoding="utf-8")

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertIn(
            "api_response_non_200 method=GET path=/api/userdetails/ "
            "status_code=401",
            log_content,
        )
