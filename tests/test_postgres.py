"""Testes para PostgresLoader — helpers de schema evolution (sem Postgres real)."""
from __future__ import annotations

from tap_ixc.loaders.postgres import _column_plan, _pg_type


class TestPgType:
    def test_known_types(self):
        assert _pg_type("BIGINT") == "BIGINT"
        assert _pg_type("INTEGER") == "BIGINT"
        assert _pg_type("VARCHAR") == "TEXT"
        assert _pg_type("BOOLEAN") == "BOOLEAN"
        assert _pg_type("DOUBLE") == "DOUBLE PRECISION"
        assert _pg_type("TIMESTAMP") == "TIMESTAMP"
        assert _pg_type("DATE") == "DATE"

    def test_decimal_maps_to_double(self):
        assert _pg_type("DECIMAL(18,2)") == "DOUBLE PRECISION"
        assert _pg_type("NUMERIC") == "DOUBLE PRECISION"

    def test_unknown_falls_back_to_text(self):
        assert _pg_type("STRUCT(a INT)") == "TEXT"
        assert _pg_type("BLOB") == "TEXT"


class TestColumnPlan:
    def test_detects_new_columns_preserving_order(self):
        target = {"id", "nome"}
        staging = ["id", "nome", "email", "cpf"]
        assert _column_plan(target, staging) == ["email", "cpf"]

    def test_no_new_columns(self):
        assert _column_plan({"id", "nome"}, ["id", "nome"]) == []

    def test_target_extra_columns_ignored(self):
        # coluna que só existe no destino não entra no plano (fica NULL no insert)
        assert _column_plan({"id", "nome", "legado"}, ["id", "nome"]) == []


class TestValidateIdentifier:
    def test_accepts_valid(self):
        from tap_ixc.loaders.base import validate_identifier
        assert validate_identifier("clientes") == "clientes"
        assert validate_identifier("fn_areceber_2") == "fn_areceber_2"

    def test_rejects_injection(self):
        import pytest
        from tap_ixc.loaders.base import validate_identifier
        for bad in ["cli; DROP TABLE x", "a b", "1abc", "tab-le", "", "x'y"]:
            with pytest.raises(ValueError):
                validate_identifier(bad)

    def test_loader_rejects_bad_table(self, tmp_path):
        import pytest
        from tap_ixc.loaders.postgres import PostgresLoader
        with pytest.raises(ValueError):
            PostgresLoader(duckdb_path=str(tmp_path/"s.duckdb"),
                           pg_dsn="postgresql://x", schema="public",
                           table="clientes; DROP TABLE y")
