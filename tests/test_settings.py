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
