"""Testes para EventStore — registro de pipeline_runs e eventos."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tap_ixc.core.events import EventStore


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


@pytest.fixture
def event_store(mock_conn):
    with patch("tap_ixc.core.events.psycopg.connect", return_value=mock_conn):
        yield EventStore("postgresql://mock/db", schema="etl"), mock_conn


class TestStartRun:
    def test_inserts_pipeline_run_and_returns_id(self, event_store):
        store, conn = event_store
        conn.execute.return_value.fetchone.return_value = (42,)

        run_id = store.start_run("gwg", "ixc", "clientes")

        assert run_id == 42
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "INSERT INTO etl.pipeline_runs" in sql

    def test_passes_correct_params(self, event_store):
        store, conn = event_store
        conn.execute.return_value.fetchone.return_value = (1,)

        store.start_run("test_client", "ixc", "test_pipeline", metadata={"foo": "bar"})

        params = conn.execute.call_args[0][1]
        assert params[0] == "test_client"
        assert params[1] == "ixc"
        assert params[2] == "test_pipeline"


class TestFinishRun:
    def test_updates_run_with_status_and_records(self, event_store):
        store, conn = event_store

        store.finish_run(
            run_id=42,
            status="SUCCESS",
            records_in=100,
            records_out=100,
        )

        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "UPDATE etl.pipeline_runs" in sql

    def test_sets_error_on_failed_run(self, event_store):
        store, conn = event_store

        store.finish_run(
            run_id=42,
            status="FAILED",
            error="API offline",
        )

        params = conn.execute.call_args[0][1]
        assert "API offline" in params


class TestEmit:
    def test_inserts_pipeline_event(self, event_store):
        store, conn = event_store

        store.emit(
            run_id=42,
            event_type="stage_done",
            stage="EXTRACT",
            message="Extracted 1000 records",
            records=1000,
        )

        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "INSERT INTO etl.pipeline_events" in sql


class TestWriteDeadLetters:
    def test_inserts_dead_letter_rows(self, event_store):
        store, conn = event_store
        mock_cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = mock_cursor

        dead = [
            {
                "record": {"id": "x", "name": "Bad"},
                "errors": {"id": ["not an integer"]},
            },
            {
                "record": {"id": "y", "name": ""},
                "errors": {"name": ["required"]},
            },
        ]

        store.write_dead_letters(run_id=42, stream="clientes", dead=dead)

        mock_cursor.executemany.assert_called_once()
        sql = mock_cursor.executemany.call_args[0][0]
        assert "INSERT INTO etl.dead_letters" in sql

    def test_empty_dead_letters_noop(self, event_store):
        store, conn = event_store
        mock_cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = mock_cursor

        store.write_dead_letters(run_id=42, stream="clientes", dead=[])

        mock_cursor.executemany.assert_not_called()
