"""DuckDB staging → Postgres destino.

Estratégias:
  full  — DROP + CREATE (substitui tudo)
  delta — DELETE WHERE pk IN staging + INSERT (upsert sem UPDATE)
"""
from __future__ import annotations

import duckdb
import structlog

from tap_ixc.loaders.base import validate_identifier

log = structlog.get_logger()


# Mapeia tipo DuckDB → tipo Postgres para ALTER TABLE ADD COLUMN (schema evolution).
_DUCKDB_TO_PG = {
    "BOOLEAN": "BOOLEAN",
    "TINYINT": "BIGINT", "SMALLINT": "BIGINT", "INTEGER": "BIGINT",
    "BIGINT": "BIGINT", "HUGEINT": "BIGINT",
    "UTINYINT": "BIGINT", "USMALLINT": "BIGINT", "UINTEGER": "BIGINT", "UBIGINT": "BIGINT",
    "FLOAT": "DOUBLE PRECISION", "DOUBLE": "DOUBLE PRECISION", "REAL": "DOUBLE PRECISION",
    "DATE": "DATE", "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP", "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
    "VARCHAR": "TEXT", "TEXT": "TEXT",
}


def _pg_type(duckdb_type: str) -> str:
    """Tipo Postgres para uma coluna nova, a partir do tipo DuckDB. TEXT é o fallback seguro."""
    base = duckdb_type.upper().split("(")[0].strip()  # DECIMAL(18,2) → DECIMAL
    if base in ("DECIMAL", "NUMERIC"):
        return "DOUBLE PRECISION"
    return _DUCKDB_TO_PG.get(base, "TEXT")


def _column_plan(target: set[str], staging: list[str]) -> list[str]:
    """Colunas presentes no staging mas ausentes no destino (a serem adicionadas)."""
    return [c for c in staging if c not in target]


class PostgresLoader:
    def __init__(
        self,
        duckdb_path: str,
        pg_dsn: str,
        schema: str,
        table: str,
        strategy: str = "full",
        pk_column: str = "id",
    ) -> None:
        self._duckdb_path = duckdb_path
        self._pg_dsn = pg_dsn
        self._schema = validate_identifier(schema, "schema")
        self._table = validate_identifier(table, "nome de tabela")
        self._strategy = strategy
        self._pk_column = validate_identifier(pk_column, "pk_column")

    @property
    def _stg(self) -> str:
        return f'pg."{self._schema}"."__stg_{self._table}"'

    @property
    def _qualified(self) -> str:
        return f'pg."{self._schema}"."{self._table}"'

    def stage(self) -> int:
        """Empurra a tabela DuckDB local para a staging compartilhada no Postgres
        (`__stg_<table>`). Roda no worker que tem o DuckDB (o do EXTRACT). Retorna count.
        """
        conn = duckdb.connect(self._duckdb_path)
        try:
            conn.execute("INSTALL postgres; LOAD postgres;")
            conn.execute("SET pg_null_byte_replacement='';")
            conn.execute(
                f"ATTACH '{self._pg_dsn}' AS pg (TYPE postgres, SCHEMA '{self._schema}')"
            )
            conn.execute(f"CREATE OR REPLACE TABLE {self._stg} AS SELECT * FROM {self._table}")
            count: int = conn.execute(f"SELECT count(*) FROM {self._stg}").fetchone()[0]  # type: ignore[index]
            conn.execute("DETACH pg")
        finally:
            conn.close()
        log.info("postgres.staged", table=self._table, schema=self._schema, records=count)
        return count

    def swap(self) -> int:
        """Troca a staging do Postgres (`__stg_<table>`) para a tabela final, atômico.
        Só fala com o Postgres (DuckDB em memória) → roda em QUALQUER worker. Retorna count.
        """
        conn = duckdb.connect()
        try:
            conn.execute("INSTALL postgres; LOAD postgres;")
            conn.execute(
                f"ATTACH '{self._pg_dsn}' AS pg (TYPE postgres, SCHEMA '{self._schema}')"
            )
            qualified, stg_remote = self._qualified, self._stg
            count: int = conn.execute(f"SELECT count(*) FROM {stg_remote}").fetchone()[0]  # type: ignore[index]

            try:
                conn.execute(f"SELECT 1 FROM {qualified} LIMIT 0")
                table_exists = True
            except duckdb.Error:
                table_exists = False

            try:
                conn.execute("BEGIN;")
                if self._strategy == "full" or not table_exists:
                    conn.execute(f"DROP TABLE IF EXISTS {qualified}")
                    conn.execute(f"CREATE TABLE {qualified} AS SELECT * FROM {stg_remote}")
                else:  # delta — evolui schema (da própria staging) e insere por nome
                    target_cols = {
                        d[0] for d in conn.execute(f"SELECT * FROM {qualified} LIMIT 0").description
                    }
                    stg_schema = {
                        r[0]: r[1] for r in conn.execute(f"DESCRIBE {stg_remote}").fetchall()
                    }
                    for col in _column_plan(target_cols, list(stg_schema)):
                        pgtype = _pg_type(stg_schema[col])
                        conn.execute(f'ALTER TABLE {qualified} ADD COLUMN IF NOT EXISTS "{col}" {pgtype}')
                        log.warning("postgres.schema_evolved", table=self._table, column=col, type=pgtype)
                    cols = ", ".join(f'"{c}"' for c in stg_schema)
                    conn.execute(
                        f"""DELETE FROM {qualified} AS tgt USING {stg_remote} AS src
                            WHERE tgt."{self._pk_column}" = src."{self._pk_column}";"""
                    )
                    conn.execute(f"INSERT INTO {qualified} ({cols}) SELECT {cols} FROM {stg_remote}")
                conn.execute("COMMIT;")
            except Exception:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {stg_remote}")
                except Exception:
                    pass
                conn.execute("DETACH pg")
        finally:
            conn.close()
        log.info(
            "postgres.loaded", table=self._table, schema=self._schema,
            strategy=self._strategy, records=count,
        )
        return count

    def load(self) -> int:
        """stage + swap num passo só (usado por runner.run / cron — staging local)."""
        self.stage()
        return self.swap()
