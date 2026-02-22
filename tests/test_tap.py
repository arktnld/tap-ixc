"""Testes para IXCTap — discover, check_connection, sync."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tap_ixc.catalog import SyncMode
from tap_ixc.config.settings import ApiConfig
from tap_ixc.tap import Destination, IXCTap


def _make_tap() -> IXCTap:
    return IXCTap(ApiConfig(
        base_url="https://api.example.com/webservice/v1",
        token="user:token",
    ))


def _make_destination(tmp_path) -> Destination:
    return Destination(
        postgres_dsn="postgresql://user:pass@localhost/db",
        schema="public",
        duckdb_path=str(tmp_path / "staging.duckdb"),
    )


class TestDiscover:
    def test_all_streams_present(self):
        tap = _make_tap()
        catalog = tap.discover()
        names = [e.stream.name for e in catalog]
        assert "clientes" in names
        assert "contratos" in names
        assert "titulos" in names

    def test_incremental_for_streams_with_replication_key(self):
        tap = _make_tap()
        catalog = tap.discover()
        for entry in catalog:
            if entry.stream.replication_key:
                assert entry.sync_mode == SyncMode.INCREMENTAL
            else:
                assert entry.sync_mode == SyncMode.FULL

    def test_catalog_select(self):
        tap = _make_tap()
        catalog = tap.discover().select("clientes")
        assert len(catalog) == 1
        assert list(catalog)[0].stream.name == "clientes"

    def test_select_invalid_stream_raises(self):
        tap = _make_tap()
        import pytest
        with pytest.raises(ValueError, match="nao_existe"):
            tap.discover().select("nao_existe")


class TestCheckConnection:
    def test_delegates_to_client(self):
        tap = _make_tap()
        with patch.object(tap._client, "check_connection", return_value=(True, None)) as mock:
            ok, err = tap.check_connection()
        mock.assert_called_once()
        assert ok is True
        assert err is None

    def test_propagates_failure(self):
        tap = _make_tap()
        with patch.object(tap._client, "check_connection", return_value=(False, "timeout")):
            ok, err = tap.check_connection()
        assert ok is False
        assert err == "timeout"


class TestSync:
    def _mock_infra(self, records_extracted=5, records_loaded=5):
        """Retorna context managers para mockar toda a infra do sync."""
        mock_checkpoint = MagicMock()
        mock_checkpoint.get_last.return_value = None

        mock_events = MagicMock()
        mock_events.start_run.return_value = 1

        mock_staging = MagicMock()
        mock_staging.load.return_value = ("/tmp/data.ndjson", records_extracted)

        mock_pg = MagicMock()
        mock_pg.load.return_value = records_loaded

        return mock_checkpoint, mock_events, mock_staging, mock_pg

    def test_returns_result_per_stream(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp, mock_ev, mock_stg, mock_pg = self._mock_infra()

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://monitor"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert len(results) == 1
        result = results[0]
        assert result.stream == "clientes"
        assert result.status == "success"
        assert result.records_extracted == 5
        assert result.records_loaded == 5

    def test_sync_all_streams(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)

        mock_cp, mock_ev, mock_stg, mock_pg = self._mock_infra()

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://monitor"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination)

        assert len(results) == 3
        assert all(r.status == "success" for r in results)

    def test_extract_failure_returns_failed(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp, mock_ev, mock_stg, mock_pg = self._mock_infra()
        mock_stg.load.side_effect = RuntimeError("API offline")

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://monitor"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert results[0].status == "failed"
        assert "API offline" in results[0].error

    def test_verify_fails_if_extracted_but_none_loaded(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp, mock_ev, mock_stg, mock_pg = self._mock_infra(
            records_extracted=10,
            records_loaded=0,
        )

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://monitor"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert results[0].status == "failed"
