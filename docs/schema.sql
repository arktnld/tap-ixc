-- Schema de monitoramento ETL (Postgres separado)

CREATE SCHEMA IF NOT EXISTS etl;

CREATE TABLE etl.pipeline_runs (
    id          SERIAL PRIMARY KEY,
    client      TEXT NOT NULL,
    system      TEXT NOT NULL,
    pipeline    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'RUNNING',
    stage       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    duration_s  REAL,
    records_in  INTEGER DEFAULT 0,
    records_out INTEGER DEFAULT 0,
    error       TEXT,
    metadata    JSONB DEFAULT '{}'
);

CREATE TABLE etl.checkpoints (
    client       TEXT NOT NULL,
    pipeline     TEXT NOT NULL,
    stage        TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_path    TEXT,
    metadata     JSONB DEFAULT '{}',
    PRIMARY KEY (client, pipeline)
);

CREATE TABLE etl.pipeline_events (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER REFERENCES etl.pipeline_runs(id),
    event_type  TEXT NOT NULL,
    stage       TEXT,
    message     TEXT,
    records     INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB DEFAULT '{}'
);

CREATE INDEX idx_runs_client ON etl.pipeline_runs(client, started_at DESC);
CREATE INDEX idx_events_run ON etl.pipeline_events(run_id, created_at);
