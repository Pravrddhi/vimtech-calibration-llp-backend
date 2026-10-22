"""Validation and serialization for authentication API payloads."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Serialize user details without exposing writable privileged fields."""

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "user_type",
            "is_staff",
            "is_active",
        )
        read_only_fields = fields


class LoginInputSerializer(serializers.Serializer):
    """Validate username and password submitted to the login endpoint."""

    username = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    role = serializers.CharField(read_only=True)


class LoginResponseSerializer(serializers.Serializer):
    """Describe the successful login response including the JWT pair."""

    message = serializers.CharField()
    user = UserSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()


class AdminUserCreateSerializer(serializers.Serializer):
    """Validate user details supplied to the admin-only creation endpoint."""

    username = serializers.CharField(
        max_length=150,
        validators=[UniqueValidator(queryset=User.objects.all())],
    )
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    user_type = serializers.ChoiceField(choices=User.UserType.choices)

    def validate(self, attrs):
        """Apply configured password rules to the proposed account."""
        candidate_user = User(
            username=attrs["username"],
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
            email=attrs.get("email", ""),
        )
        try:
            validate_password(attrs["password"], user=candidate_user)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                {"password": error.messages}
            ) from error

        return attrs

    def create(self, validated_data):
        """Create an account with privilege flags derived from its role."""
        account_data = validated_data.copy()
        user_type = account_data.pop("user_type")
        return User.objects.create_user(
            **account_data,
            user_type=user_type,
            is_staff=user_type == User.UserType.ADMIN,
            is_superuser=False,
        )


class UsernameAvailabilitySerializer(serializers.Serializer):
    """Validate the username query parameter for the availability API."""

    username = serializers.CharField(max_length=150, trim_whitespace=True)


class ChangePasswordSerializer(serializers.Serializer):
    """Validate a user's current password and proposed replacement."""

    current_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        """Verify the current password and enforce the password policy."""
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {"current_password": "The current password is incorrect."}
            )
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "The new password must be different."}
            )

        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                {"new_password": error.messages}
            ) from error

        return attrs
