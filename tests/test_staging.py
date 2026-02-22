"""Testes para StagingLoader — NDJSON → DuckDB."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from tap_ixc.loaders.staging import StagingLoader


@pytest.fixture
def tmp_duckdb(tmp_path):
    return str(tmp_path / "staging" / "staging.duckdb")


class TestStagingLoader:
    def test_load_returns_total(self, tmp_duckdb):
        loader = StagingLoader(duckdb_path=tmp_duckdb, table="clientes")
        records = [{"id": "1", "nome": "A"}, {"id": "2", "nome": "B"}]
        _, total = loader.load(iter(records))
        assert total == 2

    def test_load_empty_returns_zero(self, tmp_duckdb):
        loader = StagingLoader(duckdb_path=tmp_duckdb, table="clientes")
        _, total = loader.load(iter([]))
        assert total == 0

    def test_ndjson_written(self, tmp_duckdb):
        loader = StagingLoader(duckdb_path=tmp_duckdb, table="clientes")
        records = [{"id": "1", "nome": "Teste"}]
        path, _ = loader.load(iter(records))
        lines = Path(path).read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"id": "1", "nome": "Teste"}

    def test_duckdb_table_created(self, tmp_duckdb):
        loader = StagingLoader(duckdb_path=tmp_duckdb, table="clientes")
        records = [{"id": "1", "nome": "A"}]
        loader.load(iter(records))
        conn = duckdb.connect(tmp_duckdb)
        count = conn.execute("SELECT count(*) FROM clientes").fetchone()[0]
        conn.close()
        assert count == 1

    def test_field_selection(self, tmp_duckdb):
        loader = StagingLoader(duckdb_path=tmp_duckdb, table="clientes", fields=["id"])
        records = [{"id": "1", "nome": "A", "email": "a@a.com"}]
        loader.load(iter(records))
        conn = duckdb.connect(tmp_duckdb)
        cols = [col[0] for col in conn.execute("DESCRIBE clientes").fetchall()]
        conn.close()
        assert "id" in cols
        assert "nome" not in cols
        assert "email" not in cols

    def test_transform_sql(self, tmp_duckdb):
        loader = StagingLoader(
            duckdb_path=tmp_duckdb,
            table="clientes",
            transform_sql="SELECT id, upper(nome) AS nome FROM {raw}",
        )
        records = [{"id": "1", "nome": "empresa a"}]
        loader.load(iter(records))
        conn = duckdb.connect(tmp_duckdb)
        row = conn.execute("SELECT nome FROM clientes").fetchone()
        conn.close()
        assert row[0] == "EMPRESA A"

    def test_sanitize_applied(self, tmp_duckdb):
        """Strings vazias são convertidas para None via sanitize()."""
        loader = StagingLoader(duckdb_path=tmp_duckdb, table="clientes")
        records = [{"id": "1", "nome": ""}]
        path, _ = loader.load(iter(records))
        data = json.loads(Path(path).read_text().strip())
        assert data["nome"] is None
