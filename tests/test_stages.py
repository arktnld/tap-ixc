"""Testes para os primitivos de stage (Airflow-native)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tap_ixc import stages


def _cfg(stream="clientes", strategy="full"):
    cfg = MagicMock()
    ep = MagicMock()
    ep.name = stream
    ep.api_endpoint = "cliente"
    ep.strategy = strategy
    ep.fields = None
    ep.pk_column = "id"
    ep.transform_sql = None
    ep.page_size = 5000
    cfg.endpoints = [ep]
    cfg.postgres_dsn = "postgresql://x"
    cfg.schema_name = "public"
    cfg.api = MagicMock(base_url="https://x/v1", token="u:t", max_retries=3, timeout_s=60,
                        backoff_factor=0.5, wait_jitter=1.0, session_renewal_every=0,
                        rate_limit_sleep=0.0)
    return cfg


class TestExtract:
    def test_stages_to_pg_when_records(self):
        mock_stg = MagicMock(); mock_stg.load.return_value = ("/tmp/x.ndjson", 10)
        mock_pg = MagicMock()
        with (
            patch("tap_ixc.stages.get_client", return_value=_cfg()),
            patch("tap_ixc.stages.IXCClient"),
            patch("tap_ixc.stages.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.stages.PostgresLoader", return_value=mock_pg),
        ):
            out = stages.extract("c", "clientes", duckdb_path="/tmp/x.duckdb")
        assert out["records_extracted"] == 10
        assert out["empty"] is False
        mock_pg.stage.assert_called_once()

    def test_empty_skips_pg_stage(self):
        mock_stg = MagicMock(); mock_stg.load.return_value = ("/tmp/x.ndjson", 0)
        mock_pg = MagicMock()
        with (
            patch("tap_ixc.stages.get_client", return_value=_cfg()),
            patch("tap_ixc.stages.IXCClient"),
            patch("tap_ixc.stages.StagingLoader", return_value=mock_stg),
            patch("tap_ixc.stages.PostgresLoader", return_value=mock_pg),
        ):
            out = stages.extract("c", "clientes", duckdb_path="/tmp/x.duckdb")
        assert out["empty"] is True
        mock_pg.stage.assert_not_called()


class TestLoad:
    def test_calls_swap(self):
        mock_pg = MagicMock(); mock_pg.swap.return_value = 10
        with (
            patch("tap_ixc.stages.get_client", return_value=_cfg()),
            patch("tap_ixc.stages.PostgresLoader", return_value=mock_pg),
        ):
            out = stages.load("c", "clientes")
        assert out["records_loaded"] == 10
        mock_pg.swap.assert_called_once()


class TestVerify:
    def test_count_mismatch_raises(self):
        with patch("tap_ixc.stages.get_client", return_value=_cfg()):
            with pytest.raises(RuntimeError, match="divergente"):
                stages.verify("c", "clientes", extracted=10, loaded=7)

    def test_extracted_but_none_loaded_raises(self):
        with patch("tap_ixc.stages.get_client", return_value=_cfg()):
            with pytest.raises(RuntimeError, match="0 carregados"):
                stages.verify("c", "clientes", extracted=10, loaded=0)

    def test_ok_advances_cursor(self):
        mock_cp = MagicMock()
        with (
            patch("tap_ixc.stages.get_client", return_value=_cfg()),
            patch("tap_ixc.stages._checkpoint", return_value=mock_cp),
        ):
            out = stages.verify("c", "clientes", extracted=10, loaded=10,
                                new_cursor="2026-05-01 00:00:00")
        assert out["ok"] is True
        mock_cp.mark_done.assert_called_once()

    def test_ok_no_cursor_no_write(self):
        mock_cp = MagicMock()
        with (
            patch("tap_ixc.stages.get_client", return_value=_cfg()),
            patch("tap_ixc.stages._checkpoint", return_value=mock_cp),
        ):
            stages.verify("c", "clientes", extracted=10, loaded=10, new_cursor=None)
        mock_cp.mark_done.assert_not_called()


class TestDropStaging:
    def test_calls_loader_drop_staging(self):
        from unittest.mock import MagicMock
        mock_pg = MagicMock()
        with (
            patch("tap_ixc.stages.get_client", return_value=_cfg()),
            patch("tap_ixc.stages.PostgresLoader", return_value=mock_pg),
        ):
            stages.drop_staging("c", "clientes")
        mock_pg.drop_staging.assert_called_once()
