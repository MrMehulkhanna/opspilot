"""WSGI entry point: `gunicorn opspilot.wsgi:app`."""

from opspilot.app import create_app

app = create_app()
