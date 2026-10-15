#!/bin/sh
# Prepare the database, then hand off to the main command (gunicorn by default).
set -e
export FLASK_APP=opspilot.wsgi
flask init-db
flask load-runbooks /app/runbooks
if [ "${OPSPILOT_SEED_DEMO:-0}" = "1" ]; then
    flask seed-demo
fi
exec "$@"
