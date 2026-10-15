.PHONY: install dev test test-pg lint format seed run docker logs

PY ?= python3
FLASK = flask --app opspilot.wsgi

install:
	$(PY) -m pip install -r requirements-dev.txt -e .

test:
	pytest

# Requires a local PostgreSQL; see README.
test-pg:
	TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql://opspilot:opspilot@localhost/opspilot_test} pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

seed:
	$(FLASK) init-db
	$(FLASK) load-runbooks
	$(FLASK) seed-demo

run:
	$(FLASK) run --debug --port 5000

docker:
	docker compose up --build -d

logs:
	docker compose logs -f app
