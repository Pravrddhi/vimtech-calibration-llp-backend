"""Middleware for recording development API request metadata."""

import json
import logging
import time
from pathlib import Path

from django.conf import settings
from django.utils import timezone


LOG_DIRECTORY = Path(settings.BASE_DIR) / "dev_logs"
logger = logging.getLogger(__name__)


class ApiRequestLoggingMiddleware:
    """Write one privacy-conscious log record for each development API call."""

    def __init__(self, get_response):
        """Store the next middleware or view in Django's request chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Log API response metadata to a file named for the current date."""
        started_at = time.perf_counter()
        response = None
        try:
            response = self.get_response(request)
            return response
        except Exception as error:
            if request.path.startswith("/api/"):
                logger.error(
                    "api_request_exception exception_type=%s",
                    type(error).__name__,
                )
            raise
        finally:
            if settings.DEBUG and request.path.startswith("/api/"):
                status_code = getattr(response, "status_code", 500)
                if status_code != 200:
                    logger.error(
                        "api_response_non_200 method=%s path=%s "
                        "status_code=%s",
                        request.method,
                        request.path,
                        status_code,
                    )
                self._write_log_record(
                    request,
                    response,
                    time.perf_counter() - started_at,
                )

    @staticmethod
    def _write_log_record(request, response, duration):
        """Append request metadata without query strings or body contents."""
        logged_at = timezone.localtime(timezone.now())
        user = getattr(request, "user", None)
        record = {
            "timestamp": logged_at.isoformat(timespec="milliseconds"),
            "method": request.method,
            "path": request.path,
            "user_id": (
                user.pk
                if user is not None and user.is_authenticated
                else None
            ),
            "status_code": getattr(response, "status_code", 500),
            "duration_ms": round(duration * 1000, 2),
            "request_content_type": request.META.get("CONTENT_TYPE"),
            "response_content_type": (
                response.get("Content-Type") if response is not None else None
            ),
        }

        LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIRECTORY / f"api-{logged_at:%Y-%m-%d}.log"
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, separators=(",", ":")) + "\n")
