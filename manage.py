#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'salon_booking.settings')
    try:
        from django.core.management import execute_from_command_line
        from django.core.servers import basehttp
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    class QuietWSGIRequestHandler(basehttp.WSGIRequestHandler):
        """Ignore client disconnect errors to keep the dev server quiet."""

        def handle(self):
            try:
                super().handle()
            except (ConnectionAbortedError, BrokenPipeError):
                # Browsers may cancel requests (e.g. when navigating away)
                # which raises noisy traceback logs in the dev server.
                # Silently close the connection instead so developers are
                # not distracted by harmless stack traces during local runs.
                self.close_connection = True

    basehttp.WSGIRequestHandler = QuietWSGIRequestHandler
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
