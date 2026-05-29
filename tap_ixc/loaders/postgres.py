"""DuckDB staging → Postgres destino.

Estratégias:
  full  — DROP + CREATE (substitui tudo)
  delta — DELETE WHERE pk IN staging + INSERT (upsert sem UPDATE)
"""
from __future__ import annotations

import duckdb
import structlog

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
        self._schema = schema
        self._table = table
        self._strategy = strategy
        self._pk_column = pk_column

    def load(self) -> int:
        """Carrega tabela DuckDB para Postgres. Retorna count de registros."""
        conn = duckdb.connect(self._duckdb_path)
        try:
            conn.execute("INSTALL postgres; LOAD postgres;")
            conn.execute("SET pg_null_byte_replacement='';")
            conn.execute(
                f"ATTACH '{self._pg_dsn}' AS pg "
                f"(TYPE postgres, SCHEMA '{self._schema}')"
            )

            qualified = f'pg."{self._schema}"."{self._table}"'
            stg_remote = f'pg."{self._schema}"."__stg_{self._table}"'

            # Cria tabela de staging remota no Postgres
            conn.execute(
                f"CREATE OR REPLACE TABLE {stg_remote} AS "
                f"SELECT * FROM {self._table}"
            )
            count: int = conn.execute(
                f"SELECT count(*) FROM {stg_remote}"
            ).fetchone()[0]  # type: ignore[index]

            # Verifica se a tabela destino existe tentando um SELECT
            try:
                conn.execute(f"SELECT 1 FROM {qualified} LIMIT 0")
                table_exists = True
            except Exception:
                table_exists = False

            try:
                conn.execute("BEGIN;")
                if self._strategy == "full" or not table_exists:
                    # Full ou primeiro run de delta: cria do zero
                    conn.execute(f"DROP TABLE IF EXISTS {qualified}")
                    conn.execute(
                        f"CREATE TABLE {qualified} AS SELECT * FROM {stg_remote}"
                    )
                else:  # delta com tabela existente — evolui schema e insere por nome
                    target_cols = {
                        d[0]
                        for d in conn.execute(
                            f"SELECT * FROM {qualified} LIMIT 0"
                        ).description
                    }
                    stg_schema = {
                        r[0]: r[1]
                        for r in conn.execute(f"DESCRIBE {self._table}").fetchall()
                    }
                    # colunas novas na origem → adiciona no destino (não perde dado nem quebra)
                    for col in _column_plan(target_cols, list(stg_schema)):
                        pgtype = _pg_type(stg_schema[col])
                        conn.execute(
                            f'ALTER TABLE {qualified} ADD COLUMN IF NOT EXISTS "{col}" {pgtype}'
                        )
                        log.warning(
                            "postgres.schema_evolved",
                            table=self._table, column=col, type=pgtype,
                        )
                    cols = ", ".join(f'"{c}"' for c in stg_schema)
                    conn.execute(
                        f"""DELETE FROM {qualified} AS tgt
                            USING {stg_remote} AS src
                            WHERE tgt."{self._pk_column}" = src."{self._pk_column}";"""
                    )
                    conn.execute(
                        f"INSERT INTO {qualified} ({cols}) SELECT {cols} FROM {stg_remote}"
                    )
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
            "postgres.loaded",
            table=self._table,
            schema=self._schema,
            strategy=self._strategy,
            records=count,
        )
        return count
