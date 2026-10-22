#!/usr/bin/env python
"""Run Django management commands for the Vimtech Calibration backend."""

import os
import sys


def main():
    """Load the project settings and run the requested management command."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django could not be imported. Make sure dependencies are "
            "installed and the virtual environment is activated."
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
