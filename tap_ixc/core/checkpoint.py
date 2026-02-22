"""CRUD na tabela de checkpoints (Postgres)."""
from __future__ import annotations

import json
from typing import Any

import psycopg
import structlog

log = structlog.get_logger()


class Checkpoint:
    def __init__(self, dsn: str, schema: str = "etl"):
        self._dsn = dsn
        self._schema = schema

    def mark_done(
        self,
        client: str,
        pipeline: str,
        stage: str,
        data_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.checkpoints (client, pipeline, stage, data_path, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (client, pipeline)
                DO UPDATE SET
                    stage        = EXCLUDED.stage,
                    completed_at = now(),
                    data_path    = EXCLUDED.data_path,
                    metadata     = EXCLUDED.metadata
                """,
                (client, pipeline, stage, data_path, json.dumps(metadata or {})),
            )
        log.info("checkpoint.marked", client=client, pipeline=pipeline, stage=stage)

    def get_last(self, client: str, pipeline: str) -> dict[str, Any] | None:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                f"""
                SELECT stage, data_path, metadata
                FROM {self._schema}.checkpoints
                WHERE client = %s AND pipeline = %s
                """,
                (client, pipeline),
            ).fetchone()
        if row:
            return {"stage": row[0], "data_path": row[1], "metadata": row[2]}
        return None

    def clear(self, client: str, pipeline: str) -> None:
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                f"DELETE FROM {self._schema}.checkpoints WHERE client = %s AND pipeline = %s",
                (client, pipeline),
            )
        log.info("checkpoint.cleared", client=client, pipeline=pipeline)
