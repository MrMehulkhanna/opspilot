FROM python:3.15-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPSPILOT_RUNBOOK_DIR=/app/runbooks

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY opspilot ./opspilot
COPY runbooks ./runbooks
COPY sample_logs ./sample_logs
COPY docker/entrypoint.sh /entrypoint.sh
RUN pip install --no-deps . \
    && chmod +x /entrypoint.sh \
    && useradd --create-home --uid 10001 opspilot
USER opspilot

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=2)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "opspilot.wsgi:app"]
