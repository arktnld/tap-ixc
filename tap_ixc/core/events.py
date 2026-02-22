"""Gravação em etl.pipeline_runs e etl.pipeline_events (Postgres)."""
from __future__ import annotations

import json
from typing import Any

import psycopg
import structlog

log = structlog.get_logger()


class EventStore:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def start_run(
        self,
        client: str,
        system: str,
        pipeline: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                """
                INSERT INTO etl.pipeline_runs (client, system, pipeline, status, metadata)
                VALUES (%s, %s, %s, 'RUNNING', %s)
                RETURNING id
                """,
                (client, system, pipeline, json.dumps(metadata or {})),
            ).fetchone()
        assert row is not None
        run_id = row[0]
        log.info("run.started", client=client, system=system, pipeline=pipeline, run_id=run_id)
        return run_id

    def finish_run(
        self,
        run_id: int,
        status: str = "SUCCESS",
        records_in: int = 0,
        records_out: int = 0,
        error: str | None = None,
        stage: str | None = None,
    ) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                """
                UPDATE etl.pipeline_runs
                SET status      = %s,
                    finished_at = now(),
                    duration_s  = EXTRACT(EPOCH FROM (now() - started_at)),
                    records_in  = %s,
                    records_out = %s,
                    error       = %s,
                    stage       = %s
                WHERE id = %s
                """,
                (status, records_in, records_out, error, stage, run_id),
            )
        log.info("run.finished", run_id=run_id, status=status, records_out=records_out)

    def emit(
        self,
        run_id: int,
        event_type: str,
        stage: str | None = None,
        message: str | None = None,
        records: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                """
                INSERT INTO etl.pipeline_events
                    (run_id, event_type, stage, message, records, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (run_id, event_type, stage, message, records, json.dumps(metadata or {})),
            )
        log.debug("event.emitted", run_id=run_id, event_type=event_type, stage=stage)
