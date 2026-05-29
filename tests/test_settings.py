"""Testes para config/settings — carga de clientes."""
from __future__ import annotations

from pathlib import Path

import pytest

from tap_ixc.config.settings import load_clients


def test_missing_clients_yml_gives_actionable_error(tmp_path):
    missing = tmp_path / "nao_existe.yml"
    with pytest.raises(FileNotFoundError, match="clients.yml.example"):
        load_clients(missing)


def test_empty_clients_yml_raises(tmp_path):
    empty = tmp_path / "clients.yml"
    empty.write_text("")
    with pytest.raises(ValueError, match="vazia"):
        load_clients(empty)


def test_unresolved_env_var_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("FOO_TOKEN_XYZ", raising=False)
    yml = tmp_path / "c.yml"
    yml.write_text(
        'acme:\n'
        '  system: ixc\n'
        '  schema_name: public\n'
        '  postgres_dsn: "postgresql://u:p@localhost/db"\n'
        '  duckdb_path: "/tmp/a.duckdb"\n'
        '  api:\n'
        '    base_url: "https://x/v1"\n'
        '    token: "${FOO_TOKEN_XYZ}"\n'
        '  endpoints: []\n'
    )
    from tap_ixc.config.settings import get_client
    import pytest
    with pytest.raises(ValueError, match="FOO_TOKEN_XYZ"):
        get_client("acme", yml)


def test_literal_token_and_dsn_accepted(tmp_path):
    from tap_ixc.config.settings import get_client
    yml = tmp_path / "c.yml"
    yml.write_text(
        'acme:\n'
        '  system: ixc\n'
        '  schema_name: public\n'
        '  postgres_dsn: "postgresql://u:p@localhost/db"\n'
        '  duckdb_path: "/tmp/a.duckdb"\n'
        '  api:\n'
        '    base_url: "https://x/v1"\n'
        '    token: "10:literal_token"\n'
        '  endpoints: []\n'
    )
    cfg = get_client("acme", yml)
    assert cfg.api.token == "10:literal_token"


def test_malformed_yaml_raises_clear(tmp_path):
    import pytest
    bad = tmp_path / "c.yml"
    bad.write_text("foo: [1, 2\nbar: }{")
    with pytest.raises(ValueError, match="YAML"):
        load_clients(bad)
