"""Views for authentication and user account management."""

import logging

from django.contrib.auth import authenticate, update_session_auth_hash
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import OpenApiResponse, extend_schema

from .models import User
from .permissions import IsApplicationAdmin
from .serializers import (
    AdminUserCreateSerializer,
    ChangePasswordSerializer,
    LoginInputSerializer,
    LoginResponseSerializer,
    UsernameAvailabilitySerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


class LoginView(APIView):
    """Authenticate a user and return a refresh/access token pair."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=LoginInputSerializer,
        responses={
            200: LoginResponseSerializer,
            400: OpenApiResponse(description="Invalid request data."),
            401: OpenApiResponse(description="Invalid username or password."),
        },
        description="Authenticate with username and password to receive JWTs.",
    )
    def post(self, request):
        """Validate credentials and return user details with signed JWTs."""
        serializer = LoginInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request=request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            logger.warning("authentication_failed event=login")
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        elif user.user_type != request.data['role']:
            logger.warning(
                            "Invalid Role event=login user_id=%s",
                            user.pk,
                        )
            return Response(
                            {"detail": "Invalid Role."},
                            status=status.HTTP_401_UNAUTHORIZED,
                        )

        logger.info(
            "authentication_succeeded event=login user_id=%s",
            user.pk,
        )
        refresh = RefreshToken.for_user(user)
        refresh["user_type"] = user.user_type
        refresh["username"] = user.username

        return Response(
            {
                "message": "Login successful.",
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )


class AdminUserCreateView(APIView):
    """Create accounts through the authorized admin workflow."""

    permission_classes = [IsAuthenticated, IsApplicationAdmin]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "user_create"

    @extend_schema(
        request=AdminUserCreateSerializer,
        responses={
            201: UserSerializer,
            400: OpenApiResponse(description="Invalid user or password data."),
            401: OpenApiResponse(description="Authentication is required."),
            403: OpenApiResponse(
                description="Application admin access required."
            ),
        },
        description=(
            "Create an account. Only active users with user_type=admin and "
            "is_staff=true may use this endpoint. Only Django superusers "
            "may create another application admin."
        ),
    )
    def post(self, request):
        """Create a role-controlled account without issuing JWTs."""
        serializer = AdminUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        requested_user_type = serializer.validated_data["user_type"]
        if (
            requested_user_type == User.UserType.ADMIN
            and not request.user.is_superuser
        ):
            return Response(
                {
                    "detail": (
                        "Only a Django superuser may create an "
                        "application admin."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        user = serializer.save()

        logger.info(
            "user_created actor_id=%s user_id=%s user_type=%s",
            request.user.pk,
            user.pk,
            user.user_type,
        )
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class UsernameAvailabilityView(APIView):
    """Check username availability for authorized account administrators."""

    permission_classes = [IsAuthenticated, IsApplicationAdmin]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "user_create"

    @extend_schema(
        parameters=[UsernameAvailabilitySerializer],
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "available": {"type": "boolean"},
                    },
                    "required": ["username", "available"],
                },
                description="Username availability result.",
            ),
            400: OpenApiResponse(description="A valid username is required."),
            401: OpenApiResponse(description="Authentication is required."),
            403: OpenApiResponse(
                description="Application admin access required."
            ),
        },
        description=(
            "Check whether a username can be used when creating an account. "
            "Only active application admins may use this endpoint."
        ),
    )
    def get(self, request):
        """Return whether the supplied username is currently available."""
        serializer = UsernameAvailabilitySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        available = not User.objects.filter(username=username).exists()
        return Response(
            {"username": username, "available": available},
            status=status.HTTP_200_OK,
        )


class UserDetailsView(APIView):
    """Return details for only the authenticated user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=UserSerializer,
        description="Return the profile for the authenticated user.",
    )
    def get(self, request):
        """Serialize the authenticated user's profile."""
        return Response(
            UserSerializer(request.user).data,
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    """Change the authenticated user's password and revoke refresh tokens."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_change"

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={
            200: OpenApiResponse(description="Password updated successfully."),
            400: OpenApiResponse(
                description="Current password or new password is invalid."
            ),
            401: OpenApiResponse(description="Authentication is required."),
        },
        description=(
            "Change the authenticated user's password. Outstanding refresh "
            "tokens are blacklisted; current access tokens expire normally."
        ),
    )
    def post(self, request):
        """Verify the current password and store a validated new password."""
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError:
            logger.warning(
                "password_change_failed user_id=%s",
                request.user.pk,
            )
            raise

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        with transaction.atomic():
            user.save(update_fields=["password"])
            update_session_auth_hash(request, user)
            self._revoke_refresh_tokens(user)

        logger.info("password_changed user_id=%s", user.pk)
        return Response(
            {"message": "Password updated successfully."},
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _revoke_refresh_tokens(user):
        """Blacklist every outstanding refresh token issued to the user."""
        for outstanding_token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding_token)
