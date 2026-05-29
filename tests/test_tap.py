"""Testes para IXCTap — discover, check_connection, sync."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tap_ixc.catalog import SyncMode
from tap_ixc.config.settings import ApiConfig
from tap_ixc.streams import ClienteStream
from tap_ixc.streams.base import Stream
from tap_ixc.tap import Destination, IXCTap, _advance_cursor


def test_api_config_new_fields_have_defaults():
    cfg = ApiConfig(base_url="http://x", token="t")
    assert cfg.wait_jitter == 1.0
    assert cfg.session_renewal_every == 0
    assert cfg.rate_limit_sleep == 0.0


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


def test_advance_cursor():
    assert _advance_cursor(None, "2026-05-01 00:00:00") == "2026-05-01 00:00:00"
    assert _advance_cursor("2026-05-01 00:00:00", "2026-04-01 00:00:00") == "2026-05-01 00:00:00"
    assert _advance_cursor("2026-05-01 00:00:00", "2026-06-01 00:00:00") == "2026-06-01 00:00:00"
    assert _advance_cursor("2026-05-01 00:00:00", None) == "2026-05-01 00:00:00"
    assert _advance_cursor("2026-05-01 00:00:00", "") == "2026-05-01 00:00:00"
    assert _advance_cursor(None, None) is None


class TestIncrementalCursor:
    """Cursor incremental: lê o último valor salvo e só avança após sucesso total."""

    def _patches(self, mock_cp, mock_ev, mock_stg, mock_pg, fake_records):
        return (
            patch("tap_ixc.tap.Settings"),
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
            patch.object(Stream, "get_records", side_effect=fake_records),
        )

    def _infra(self):
        mock_cp = MagicMock()
        mock_ev = MagicMock()
        mock_ev.start_run.return_value = 1
        mock_stg = MagicMock()
        mock_pg = MagicMock()
        mock_pg.load.return_value = 3

        # staging consome o iterador de verdade → dispara o tracking do cursor
        def consuming_load(records):
            n = len(list(records))
            return ("/tmp/x.ndjson", n)

        mock_stg.load.side_effect = consuming_load
        return mock_cp, mock_ev, mock_stg, mock_pg

    def test_reads_saved_cursor_and_advances_to_max(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp, mock_ev, mock_stg, mock_pg = self._infra()
        mock_cp.get_last.return_value = {
            "stage": "VERIFY",
            "data_path": None,
            "metadata": {"replication_key_value": "2026-05-01 00:00:00"},
        }

        captured = {}

        def fake_records(client, sync_mode, since=None, page_size=None):
            captured["since"] = since
            return iter([
                {"id": 1, "ultima_atualizacao": "2026-05-10 08:00:00"},
                {"id": 2, "ultima_atualizacao": "2026-05-12 09:30:00"},
                {"id": 3, "ultima_atualizacao": "2026-05-11 07:00:00"},
            ])

        p1, p2, p3, p4, p5, p6 = self._patches(mock_cp, mock_ev, mock_stg, mock_pg, fake_records)
        with p1 as MockSettings, p2, p3, p4, p5, p6:
            MockSettings.return_value.monitor_dsn = "postgresql://monitor"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert results[0].status == "success"
        # leu o cursor salvo e passou como since
        assert captured["since"] == "2026-05-01 00:00:00"
        # persistiu o maior ultima_atualizacao visto
        mock_cp.mark_done.assert_any_call(
            "default", "clientes", "VERIFY",
            data_path="/tmp/x.ndjson",
            metadata={"replication_key_value": "2026-05-12 09:30:00"},
        )

    def test_first_run_has_no_cursor(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp, mock_ev, mock_stg, mock_pg = self._infra()
        mock_cp.get_last.return_value = None

        captured = {}

        def fake_records(client, sync_mode, since=None, page_size=None):
            captured["since"] = since
            return iter([{"id": 1, "ultima_atualizacao": "2026-05-10 08:00:00"}])

        p1, p2, p3, p4, p5, p6 = self._patches(mock_cp, mock_ev, mock_stg, mock_pg, fake_records)
        with p1 as MockSettings, p2, p3, p4, p5, p6:
            MockSettings.return_value.monitor_dsn = "postgresql://monitor"
            MockSettings.return_value.monitor_schema = "etl"
            tap.sync(destination, catalog)

        # primeiro run: sem cursor salvo → since None (client cai no default do IXCClient)
        assert captured["since"] is None


class TestValidateStage:
    """Stage VALIDATE: só roda com schema; reprovadas vão para dead letter."""

    def _consuming_load(self, records):
        return ("/tmp/x.ndjson", len(list(records)))

    def test_skipped_when_no_schema(self, tmp_path):
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp = MagicMock(); mock_cp.get_last.return_value = None
        mock_ev = MagicMock(); mock_ev.start_run.return_value = 1
        mock_stg = MagicMock(); mock_stg.load.side_effect = self._consuming_load
        mock_pg = MagicMock(); mock_pg.load.return_value = 1

        def fake_records(client, sync_mode, since=None, page_size=None):
            return iter([{"id": 1, "ultima_atualizacao": "2026-05-10 00:00:00"}])

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
            patch.object(Stream, "get_records", side_effect=fake_records),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://m"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert results[0].status == "success"
        # sem schema → VALIDATE não roda
        mock_stg.read_all.assert_not_called()
        mock_stg.replace.assert_not_called()
        mock_ev.write_dead_letters.assert_not_called()

    def test_runs_when_schema_present_and_dead_letters_written(self, tmp_path):
        from pydantic import BaseModel

        class ClienteSchema(BaseModel):
            id: int
            nome: str = ""

        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp = MagicMock(); mock_cp.get_last.return_value = None
        mock_ev = MagicMock(); mock_ev.start_run.return_value = 7
        mock_stg = MagicMock(); mock_stg.load.side_effect = self._consuming_load
        # 1 válida, 1 inválida (id não-inteiro)
        mock_stg.read_all.return_value = [
            {"id": 1, "nome": "Joao"},
            {"id": "xx", "nome": "Maria"},
        ]
        mock_pg = MagicMock(); mock_pg.load.return_value = 1

        def fake_records(client, sync_mode, since=None, page_size=None):
            return iter([{"id": 1, "nome": "Joao", "ultima_atualizacao": "2026-05-10 00:00:00"}])

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
            patch.object(Stream, "get_records", side_effect=fake_records),
            patch.object(ClienteStream, "schema", ClienteSchema),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://m"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert results[0].status == "success"
        # dead letter: run_id 7, stream clientes, 1 linha reprovada
        mock_ev.write_dead_letters.assert_called_once()
        run_id, stream_name, dead = mock_ev.write_dead_letters.call_args[0]
        assert run_id == 7
        assert stream_name == "clientes"
        assert len(dead) == 1
        assert dead[0]["record"]["id"] == "xx"
        # staging.replace recebe só a válida
        mock_stg.replace.assert_called_once()
        valid = mock_stg.replace.call_args[0][0]
        assert len(valid) == 1
        assert valid[0]["id"] == 1


class TestEmptyAndResume:
    """Regressão: extração vazia e resume via --from-checkpoint."""

    def test_empty_extract_is_noop_success(self, tmp_path):
        # Bug: extração vazia (incremental sem mudanças) quebrava o LOAD.
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp = MagicMock(); mock_cp.get_last.return_value = None
        mock_ev = MagicMock(); mock_ev.start_run.return_value = 1
        mock_stg = MagicMock(); mock_stg.load.return_value = ("/tmp/x.ndjson", 0)  # vazio
        mock_pg = MagicMock()

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://m"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog)

        assert results[0].status == "success"
        assert results[0].records_loaded == 0
        mock_pg.load.assert_not_called()  # LOAD pulado — não dropa a tabela à toa

    def test_resume_skips_extract_verify_passes(self, tmp_path):
        # Bug: VERIFY de contagem dava falso erro no resume (EXTRACT pulado).
        tap = _make_tap()
        destination = _make_destination(tmp_path)
        catalog = tap.discover().select("clientes")

        mock_cp = MagicMock()
        mock_cp.get_last.return_value = {
            "stage": "EXTRACT", "data_path": "/tmp/x.ndjson", "metadata": {},
        }
        mock_ev = MagicMock(); mock_ev.start_run.return_value = 1
        mock_stg = MagicMock(); mock_stg.load.return_value = ("/tmp/x.ndjson", 5)
        mock_pg = MagicMock(); mock_pg.load.return_value = 5

        with (
            patch("tap_ixc.tap.Settings") as MockSettings,
            patch("tap_ixc.tap.Checkpoint", return_value=mock_cp),
            patch("tap_ixc.tap.EventStore", return_value=mock_ev),
            patch("tap_ixc.tap.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.tap.PostgresLoader", return_value=mock_pg),
        ):
            MockSettings.return_value.monitor_dsn = "postgresql://m"
            MockSettings.return_value.monitor_schema = "etl"
            results = tap.sync(destination, catalog, from_checkpoint=True)

        assert results[0].status == "success"
        mock_stg.load.assert_not_called()  # EXTRACT pulado
        mock_pg.load.assert_called_once()  # LOAD rodou lendo o staging anterior
