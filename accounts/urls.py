"""URL routes for authentication and user profile APIs."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .views import (
    AdminUserCreateView,
    ChangePasswordView,
    LoginView,
    UserDetailsView,
    UsernameAvailabilityView,
)


urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path(
        "users/check-username/",
        UsernameAvailabilityView.as_view(),
        name="check-username",
    ),
    path("users/", AdminUserCreateView.as_view(), name="user-create"),
    path(
        "userdetails/",
        UserDetailsView.as_view(),
        name="userdetails",
    ),
    path(
        "userdetails/change-password/",
        ChangePasswordView.as_view(),
        name="change-password",
    ),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token_verify"),
]
