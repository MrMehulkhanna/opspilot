-- OpsPilot schema. Written once, rendered for PostgreSQL or SQLite by
-- opspilot.db: {{ID}} becomes an auto-increment primary key column type.
-- All timestamps are stored as UTC without a zone.

CREATE TABLE IF NOT EXISTS services (
    id          {{ID}},
    name        VARCHAR(80)  NOT NULL UNIQUE,
    team        VARCHAR(80)  NOT NULL,
    tier        SMALLINT     NOT NULL DEFAULT 2 CHECK (tier BETWEEN 1 AND 3),
    created_at  TIMESTAMP    NOT NULL
);

CREATE TABLE IF NOT EXISTS engineers (
    id          {{ID}},
    name        VARCHAR(120) NOT NULL,
    email       VARCHAR(200) NOT NULL UNIQUE,
    role        VARCHAR(20)  NOT NULL DEFAULT 'engineer'
                CHECK (role IN ('engineer', 'lead')),
    created_at  TIMESTAMP    NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id               {{ID}},
    service_id       INTEGER      NOT NULL REFERENCES services(id),
    title            VARCHAR(200) NOT NULL,
    severity         VARCHAR(4)   NOT NULL CHECK (severity IN ('SEV1', 'SEV2', 'SEV3')),
    status           VARCHAR(16)  NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open', 'acknowledged', 'investigating',
                                       'resolved', 'closed')),
    error_count      INTEGER      NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    sample_message   TEXT,
    assignee_id      INTEGER      REFERENCES engineers(id),
    opened_at        TIMESTAMP    NOT NULL,
    acknowledged_at  TIMESTAMP,
    resolved_at      TIMESTAMP,
    closed_at        TIMESTAMP,
    ack_due_at       TIMESTAMP    NOT NULL,
    resolve_due_at   TIMESTAMP    NOT NULL,
    resolution_note  TEXT,
    CHECK (ack_due_at > opened_at),
    CHECK (resolve_due_at >= ack_due_at),
    CHECK (resolved_at IS NULL OR resolved_at >= opened_at),
    CHECK (status <> 'closed' OR closed_at IS NOT NULL)
);

-- At most one active incident per service: repeated spikes attach to it
-- instead of creating duplicates. Partial indexes work on both engines.
CREATE UNIQUE INDEX IF NOT EXISTS uq_incidents_one_active_per_service
    ON incidents (service_id)
    WHERE status IN ('open', 'acknowledged', 'investigating');

CREATE INDEX IF NOT EXISTS ix_incidents_status_severity
    ON incidents (status, severity);
CREATE INDEX IF NOT EXISTS ix_incidents_service_opened
    ON incidents (service_id, opened_at);

-- Append-only audit trail for everything that happens to an incident.
CREATE TABLE IF NOT EXISTS incident_events (
    id           {{ID}},
    incident_id  INTEGER     NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    actor_id     INTEGER     REFERENCES engineers(id),
    kind         VARCHAR(24) NOT NULL
                 CHECK (kind IN ('created', 'spike', 'status_change', 'assigned',
                                 'comment', 'ai_suggested', 'ai_approved',
                                 'ai_edited', 'ai_rejected')),
    from_status  VARCHAR(16),
    to_status    VARCHAR(16),
    detail       TEXT,
    created_at   TIMESTAMP   NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_incident_created
    ON incident_events (incident_id, created_at);

CREATE TABLE IF NOT EXISTS runbooks (
    id           {{ID}},
    slug         VARCHAR(80)  NOT NULL UNIQUE,
    title        VARCHAR(200) NOT NULL,
    service_tag  VARCHAR(80),
    body         TEXT         NOT NULL,
    updated_at   TIMESTAMP    NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_suggestions (
    id              {{ID}},
    incident_id     INTEGER      NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    source          VARCHAR(8)   NOT NULL CHECK (source IN ('llm', 'rules')),
    model           VARCHAR(80),
    probable_cause  TEXT         NOT NULL,
    suggested_steps TEXT         NOT NULL,
    suggested_severity VARCHAR(4) CHECK (suggested_severity IN ('SEV1', 'SEV2', 'SEV3')),
    status          VARCHAR(10)  NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'edited', 'rejected')),
    final_steps     TEXT,
    reviewed_by     INTEGER      REFERENCES engineers(id),
    reviewed_at     TIMESTAMP,
    review_comment  TEXT,
    created_at      TIMESTAMP    NOT NULL,
    CHECK (status = 'pending' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ix_suggestions_incident_created
    ON ai_suggestions (incident_id, created_at);
CREATE INDEX IF NOT EXISTS ix_suggestions_status_source
    ON ai_suggestions (status, source);

-- Which runbooks were retrieved for a suggestion, with their BM25 rank/score.
CREATE TABLE IF NOT EXISTS suggestion_runbooks (
    suggestion_id  INTEGER NOT NULL REFERENCES ai_suggestions(id) ON DELETE CASCADE,
    runbook_id     INTEGER NOT NULL REFERENCES runbooks(id),
    rank           SMALLINT NOT NULL CHECK (rank >= 1),
    score          REAL     NOT NULL,
    PRIMARY KEY (suggestion_id, runbook_id),
    UNIQUE (suggestion_id, rank)
);

-- One row per analyzed log batch.
CREATE TABLE IF NOT EXISTS log_ingests (
    id               {{ID}},
    source           VARCHAR(200) NOT NULL,
    lines_total      INTEGER NOT NULL CHECK (lines_total >= 0),
    lines_parsed     INTEGER NOT NULL CHECK (lines_parsed >= 0),
    error_lines      INTEGER NOT NULL CHECK (error_lines >= 0),
    spikes_detected  INTEGER NOT NULL CHECK (spikes_detected >= 0),
    created_at       TIMESTAMP NOT NULL,
    CHECK (lines_parsed <= lines_total)
);
