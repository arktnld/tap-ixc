"""Testes para etl.core.checkpoint com mock de psycopg."""
from unittest.mock import MagicMock, patch

import pytest

from tap_ixc.core.checkpoint import Checkpoint


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


@pytest.fixture
def cp(mock_conn):
    with patch("tap_ixc.core.checkpoint.psycopg.connect", return_value=mock_conn):
        yield Checkpoint("postgresql://mock/db"), mock_conn


class TestCheckpoint:
    def test_mark_done(self, cp):
        checkpoint, conn = cp
        checkpoint.mark_done("gwg", "clientes", "EXTRACT")
        conn.execute.assert_called_once()
        sql, params = conn.execute.call_args[0]
        assert "INSERT INTO etl.checkpoints" in sql
        assert params[0] == "gwg"
        assert params[1] == "clientes"
        assert params[2] == "EXTRACT"

    def test_get_last_returns_none_when_missing(self, cp):
        checkpoint, conn = cp
        conn.execute.return_value.fetchone.return_value = None
        result = checkpoint.get_last("gwg", "clientes")
        assert result is None

    def test_get_last_returns_dict(self, cp):
        checkpoint, conn = cp
        conn.execute.return_value.fetchone.return_value = ("EXTRACT", "/tmp/x.ndjson", {})
        result = checkpoint.get_last("gwg", "clientes")
        assert result == {"stage": "EXTRACT", "data_path": "/tmp/x.ndjson", "metadata": {}}

    def test_clear(self, cp):
        checkpoint, conn = cp
        checkpoint.clear("gwg", "clientes")
        conn.execute.assert_called_once()
        sql, params = conn.execute.call_args[0]
        assert "DELETE FROM etl.checkpoints" in sql
        assert params == ("gwg", "clientes")
