# OpsPilot

**AI-assisted incident triage and support desk for production-support teams.**

OpsPilot reads application logs, notices when a service starts throwing errors, and opens an
incident with SLA deadlines. Incidents move through a fixed lifecycle. For each incident an AI
assistant drafts a probable cause and next steps from the team's own runbooks. Nothing the AI
suggests is used until an engineer approves, edits or rejects it, and every action is recorded
in an audit trail.

[![CI](https://github.com/MrMehulkhanna/opspilot/actions/workflows/ci.yml/badge.svg)](https://github.com/MrMehulkhanna/opspilot/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Flask](https://img.shields.io/badge/flask-3-black)
![PostgreSQL](https://img.shields.io/badge/postgresql-16-336791)
![License](https://img.shields.io/badge/license-MIT-green)

![Incident queue](docs/screenshots/dashboard.png)

## What it does

| Area | Details |
| --- | --- |
| **Log analyzer** | Parses plain-text and JSON log lines, then runs a per-service **sliding-window** error counter. A service with `N` errors inside any `W`-second window opens an incident. Hysteresis stops a rate that hovers near the threshold from opening duplicate incidents. |
| **Incident lifecycle** | `open → acknowledged → investigating → resolved → closed`, plus reopen. Illegal moves are rejected, and resolving requires a note. Severity sets the acknowledge and resolve **SLA deadlines**. |
| **Database** | Normalized PostgreSQL schema with foreign keys, `CHECK` and `UNIQUE` constraints, composite indexes and a **partial unique index** that allows only one active incident per service. All queries are **hand-written SQL**, with no ORM. |
| **Reports** | `JOIN` / `GROUP BY` / `CASE` queries for **SLA breaches**, **mean time to acknowledge/resolve**, **AI acceptance rate** and runbook usefulness. |
| **AI triage (RAG)** | A from-scratch **BM25** retriever ranks runbooks for the incident. An **LLM** writes a suggestion grounded in those runbooks. If the LLM is unavailable or its reply fails validation, a **rule-based** triager takes over. |
| **Human-in-the-loop** | An engineer approves, edits or rejects every suggestion. Each decision is **audited** with who made it and when. |
| **Quality** | 122 pytest tests run in **GitHub Actions** against **both SQLite and PostgreSQL**, plus ruff linting and a Docker Compose smoke test. |

## Screenshots

| Incident with AI triage awaiting review | Reports |
| --- | --- |
| ![Incident](docs/screenshots/incident.png) | ![Reports](docs/screenshots/reports.png) |

## Architecture

```mermaid
flowchart LR
    logs[(Application logs)] -->|upload / API / CLI| parser[Log parser]
    parser --> window[Sliding-window<br/>spike detector]
    window -->|spike| inc[Incident service<br/>lifecycle + SLA]
    inc --> db[(PostgreSQL)]
    inc --> audit[Audit events]
    audit --> db

    inc -->|triage| rag[BM25 runbook<br/>retrieval]
    rag --> llm{LLM available<br/>and valid reply?}
    llm -->|yes| sug[Suggestion: pending]
    llm -->|no| rules[Rule-based triage] --> sug
    sug --> eng((Engineer))
    eng -->|approve / edit / reject| audit

    db --> reports[SQL reports<br/>SLA · MTTR · AI acceptance]
    reports --> ui[Dashboard + REST API]
```

The code is split into small layers. `store/` holds the SQL, `incidents.py` and `lifecycle.py` hold
the business rules, and `api/` and `web/` are thin HTTP adapters over the same functions. Each request
runs as one database transaction.

### Data model

```mermaid
erDiagram
    services ||--o{ incidents : has
    engineers ||--o{ incidents : "assigned to"
    incidents ||--o{ incident_events : "audit trail"
    engineers ||--o{ incident_events : performs
    incidents ||--o{ ai_suggestions : receives
    engineers ||--o{ ai_suggestions : reviews
    ai_suggestions ||--o{ suggestion_runbooks : cites
    runbooks ||--o{ suggestion_runbooks : "retrieved as"
```

Some of the constraints in [`opspilot/schema.sql`](opspilot/schema.sql):

- `CHECK (severity IN ('SEV1','SEV2','SEV3'))`, `CHECK (status IN (...))`, `CHECK (resolve_due_at >= ack_due_at)`
- A suggestion can't be marked reviewed without a reviewer and a timestamp:
  `CHECK (status = 'pending' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))`
- `UNIQUE (suggestion_id, rank)` on the retrieval table
- A partial unique index that allows one active incident per service. The database enforces this even if two log batches race:
  ```sql
  CREATE UNIQUE INDEX uq_incidents_one_active_per_service
      ON incidents (service_id)
      WHERE status IN ('open', 'acknowledged', 'investigating');
  ```
- Composite indexes for the hot paths: `(status, severity)`, `(service_id, opened_at)`, `(incident_id, created_at)`

### Example report query

From [`opspilot/reports.py`](opspilot/reports.py). An incident counts as breached as soon as its
deadline passes, not only once it is finally handled:

```sql
SELECT s.name   AS service,
       i.severity,
       COUNT(*) AS incidents,
       SUM(CASE WHEN COALESCE(i.acknowledged_at, :now) > i.ack_due_at
                THEN 1 ELSE 0 END) AS ack_breaches,
       SUM(CASE WHEN COALESCE(i.resolved_at, :now) > i.resolve_due_at
                THEN 1 ELSE 0 END) AS resolve_breaches
FROM incidents i
JOIN services s ON s.id = i.service_id
WHERE i.opened_at >= :since
GROUP BY s.name, i.severity
ORDER BY resolve_breaches DESC, ack_breaches DESC;
```

## How the pieces work

### Spike detection

Each service has a deque of recent error timestamps. Every new error is appended, and entries older
than `W` seconds are dropped from the front, so the deque length is always the error count in the last
`W` seconds. Each error costs O(1) amortized time. When the count reaches the threshold, a spike
*episode* starts. The episode ends only when the count falls below half the threshold. Without that
margin, a rate hovering around the threshold would open many duplicate incidents.

Severity comes from how far the peak overshot the threshold: at least 4× is SEV1, at least 2× is
SEV2, anything else is SEV3. A spike on a service that already has an active incident is added to
that incident instead of opening a new one.

### SLA policy

| Severity | Acknowledge within | Resolve within |
| --- | --- | --- |
| SEV1 | 15 min | 4 h |
| SEV2 | 30 min | 12 h |
| SEV3 | 4 h | 72 h |

### AI triage

1. **Retrieve:** the incident's service, title and most common error form a query, and
   [BM25](opspilot/triage/bm25.py) (implemented from the formula, with no library) ranks the runbooks.
2. **Generate:** the top runbooks go into a prompt asking for strict JSON (`probable_cause`, `steps`,
   `severity`). The reply is parsed and validated, and anything malformed is discarded.
3. **Fallback:** if no API key is set, the request fails or the reply is invalid, keyword rules supply
   the cause and the steps come from the top runbook. The audit event records why the fallback was used.
4. **Review:** suggestions start as `pending`. Approving keeps the steps, editing stores the engineer's
   steps, and rejecting requires a reason. A suggestion can be reviewed only once.

The **AI acceptance rate** is `(approved + edited) / reviewed`, reported separately for LLM and rule
suggestions. The "as-is" rate shows how often no edits were needed.

## Quick start

### Docker (PostgreSQL + app + demo data)

```bash
git clone https://github.com/MrMehulkhanna/opspilot.git && cd opspilot
docker compose up --build
# open http://localhost:8000
```

The container creates the schema, loads the runbooks and seeds two weeks of demo incidents. Set
`OPSPILOT_SEED_DEMO=0` to start empty. To enable LLM triage, set `ANTHROPIC_API_KEY` in `.env`.
Without it, the rule-based triager is used.

### Local (SQLite)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -e .

export FLASK_APP=opspilot.wsgi
flask init-db
flask load-runbooks
flask seed-demo                       # optional demo data
flask analyze sample_logs/app.log     # or upload logs in the dashboard
flask run --debug
```

Regenerate the sample log with `python scripts/generate_logs.py --minutes 360`.

## REST API

All endpoints live under `/api/v1` and return JSON. If `OPSPILOT_API_KEY` is set, send it as
`X-API-Key`. Engineer actions identify the engineer with `X-Engineer-Id`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness, database and LLM status |
| `POST` | `/logs/analyze` | Analyze logs: multipart `file`, JSON `{"lines": [...]}`, or raw text |
| `GET` | `/logs/ingests` | Recent analyzed batches |
| `GET` | `/incidents?status=&severity=&service=&limit=&offset=` | Filtered, paginated incident list with live SLA state |
| `POST` | `/incidents` | Open an incident manually |
| `GET` | `/incidents/{id}` | Incident with timeline, suggestions and allowed transitions |
| `POST` | `/incidents/{id}/transition` | `{"status": "...", "note": "..."}` |
| `POST` | `/incidents/{id}/assign` | `{"engineer_id": 1}` |
| `POST` | `/incidents/{id}/comments` | `{"body": "..."}` |
| `POST` | `/incidents/{id}/suggestions` | Generate an AI triage suggestion |
| `POST` | `/suggestions/{id}/review` | `{"decision": "approve" \| "edit" \| "reject", "steps": [...], "comment": "..."}` |
| `GET` | `/reports/sla-breaches?days=30` | SLA breaches by service and severity |
| `GET` | `/reports/mttr?days=30` | Mean time to acknowledge / resolve |
| `GET` | `/reports/ai-acceptance?days=30` | AI acceptance rate by source |
| `GET` | `/reports/runbooks?days=30` | Which top-ranked runbooks led to accepted suggestions |
| `GET` `POST` | `/engineers` | List / create engineers |
| `GET` | `/services`, `/runbooks` | Reference data |

Errors use a consistent shape (`{"error": "..."}`) with meaningful status codes. An illegal lifecycle
move returns `409`, bad input returns `422`, and unknown IDs return `404`.

```bash
curl -s -X POST localhost:8000/api/v1/logs/analyze -F file=@sample_logs/app.log
curl -s -X POST localhost:8000/api/v1/incidents/1/transition \
     -H 'X-Engineer-Id: 1' -H 'Content-Type: application/json' \
     -d '{"status": "acknowledged"}'
```

## Testing

```bash
pytest                                   # SQLite
TEST_DATABASE_URL=postgresql://opspilot:opspilot@localhost/opspilot_test pytest   # PostgreSQL
```

The same suite runs on both databases in CI. The tests cover lifecycle rules, schema constraints
(including the partial unique index), the parser and window edge cases, BM25 scoring, LLM reply
validation and fallback, the review workflow, every report query, the REST API, the dashboard
(including CSRF) and the CLI.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///opspilot.db` | SQLAlchemy URL; `postgresql://...` in production |
| `SECRET_KEY` | dev value | Flask session signing |
| `OPSPILOT_API_KEY` | empty | Require `X-API-Key` on the REST API when set |
| `OPSPILOT_SPIKE_WINDOW_SECONDS` | `60` | Sliding-window length |
| `OPSPILOT_SPIKE_THRESHOLD` | `10` | Errors per window that open an incident |
| `ANTHROPIC_API_KEY` | empty | Enables LLM triage |
| `OPSPILOT_LLM_MODEL` | `claude-haiku-5-5` | Model used for triage |
| `OPSPILOT_RUNBOOK_TOP_K` | `3` | Runbooks retrieved per suggestion |
| `OPSPILOT_RUNBOOK_DIR` | `./runbooks` | Where `load-runbooks` / `seed-demo` read from |

## Project layout

```
opspilot/
  schema.sql          tables, constraints, indexes (rendered per dialect)
  db.py               engine, dialect helpers, schema setup
  lifecycle.py        status transitions + SLA policy (pure functions)
  incidents.py        audited incident operations
  reports.py          SQL reports
  analyzer/           parser, sliding-window detector, ingest pipeline
  triage/             BM25, retriever, LLM client, rules, triage engine
  store/              hand-written SQL per table group
  api/                REST endpoints
  web/, templates/    dashboard
runbooks/             Markdown knowledge base for retrieval
sample_logs/          generated log with injected incidents
tests/                pytest suite (SQLite + PostgreSQL)
```

## Design decisions

- **No ORM.** Queries are short, explicit SQL, so they are easy to explain, `EXPLAIN` and index.
  SQLAlchemy is used only for connection pooling and parameter binding, which keeps one code path
  working on both SQLite and PostgreSQL. The only dialect-specific pieces are the identity column
  type and the timestamp difference used in the MTTR query.
- **Business rules are pure functions.** `lifecycle.py` has no I/O, so the rules are tested directly.
  The database repeats the critical ones as constraints.
- **The AI is advisory.** Model output is parsed and validated against a fixed shape, and a
  deterministic fallback always exists. Suggestions have no effect until an engineer reviews them,
  and the audit trail records who decided what.
- **Row locking.** On PostgreSQL, transitions lock the incident row (`SELECT ... FOR UPDATE`), so two
  engineers acting at the same moment cannot both apply a change.

## License

MIT
