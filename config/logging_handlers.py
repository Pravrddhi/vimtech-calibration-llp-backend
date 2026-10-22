"""Logging handlers for date-partitioned development log files."""

import logging
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone


LOG_DIRECTORY = Path(settings.BASE_DIR) / "dev_logs"


class DailyFileHandler(logging.Handler):
    """Append formatted application logs to a file for the current date."""

    def emit(self, record):
        """Write a log record without keeping a file handle open."""
        try:
            timestamp = datetime.fromtimestamp(
                record.created,
                tz=datetime_timezone.utc,
            )
            local_timestamp = timezone.localtime(timestamp)
            LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
            log_path = LOG_DIRECTORY / (
                f"app-{local_timestamp:%Y-%m-%d}.log"
            )
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(self.format(record) + "\n")
        except OSError:
            self.handleError(record)
