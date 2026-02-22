"""NDJSON → DuckDB persistente (nunca :memory:)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

import duckdb
import structlog

from tap_ixc.core.contracts import sanitize

log = structlog.get_logger()


class StagingLoader:
    """
    Consome um Iterator de records, grava NDJSON e carrega no DuckDB persistente.

    Se `fields` for fornecido, o DuckDB só mantém essas colunas.
    Se `transform_sql` for fornecido, substitui qualquer SELECT automático.
    """

    def __init__(
        self,
        duckdb_path: str,
        table: str,
        fields: list[str] | None = None,
        transform_sql: str | None = None,
    ) -> None:
        self._duckdb_path = duckdb_path
        self._table = table
        self._fields = fields
        self._transform_sql = transform_sql
        os.makedirs(os.path.dirname(duckdb_path), exist_ok=True)

    def _ndjson_path(self) -> Path:
        base = Path(self._duckdb_path).parent / "ndjson"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{self._table}.ndjson"

    def _select_sql(self, raw_glob: str) -> str:
        source = f"read_json_auto('{raw_glob}')"
        if self._transform_sql:
            return self._transform_sql.replace("{raw}", source)
        if self._fields:
            cols = ", ".join(f'"{f}"' for f in self._fields)
            return f"SELECT {cols} FROM {source}"
        return f"SELECT * FROM {source}"

    def load(self, records: Iterator[dict[str, Any]]) -> tuple[str, int]:
        """
        Consome o iterador, grava NDJSON sanitizado e carrega no DuckDB.
        Retorna (ndjson_path, total_records).
        """
        ndjson_path = self._ndjson_path()
        total = 0

        with open(ndjson_path, "w", encoding="utf-8") as f:
            for rec in records:
                clean = sanitize(rec)
                f.write(json.dumps(clean, ensure_ascii=False))
                f.write("\n")
                total += 1

        if total == 0:
            log.warning("staging.empty", table=self._table)
            return str(ndjson_path), 0

        glob = str(ndjson_path).replace("\\", "/")
        conn = duckdb.connect(self._duckdb_path)
        try:
            select = self._select_sql(glob)
            conn.execute(f"CREATE OR REPLACE TABLE {self._table} AS ({select})")
        finally:
            conn.close()

        log.info("staging.loaded", table=self._table, records=total)
        return str(ndjson_path), total
