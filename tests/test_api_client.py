"""Testes para IXCClient — paginação, params, check_connection."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from tap_ixc.extractors.api import IXCClient, _midnight_yesterday_sp


class TestMidnightYesterdaySP:
    def test_returns_formatted_string(self):
        result = _midnight_yesterday_sp()
        assert len(result) == 19
        assert result[10] == " "
        assert result.endswith("00:00:00")


class TestBuildParams:
    def setup_method(self):
        self.client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
            page_size=5000,
        )

    def test_full_strategy(self):
        params = self.client._build_params("cliente", page=1, strategy="full", incremental_since=None)
        assert params["page"] == "1"
        assert params["rp"] == "5000"
        assert params["oper"] == ">="
        assert params["query"] == "0"
        assert "cliente.id" in params["qtype"]

    def test_full_strategy_page_2(self):
        params = self.client._build_params("cliente", page=2, strategy="full", incremental_since=None)
        assert params["page"] == "2"

    def test_delta_strategy_with_since(self):
        params = self.client._build_params(
            "cliente", page=1, strategy="delta", incremental_since="2024-01-01 00:00:00"
        )
        assert params["query"] == "2024-01-01 00:00:00"
        assert params["oper"] == ">="
        assert "ultima_atualizacao" in params["qtype"]

    def test_delta_without_since_uses_yesterday(self):
        params = self.client._build_params("cliente", page=1, strategy="delta", incremental_since=None)
        assert params["query"].endswith("00:00:00")

    def test_custom_rp(self):
        params = self.client._build_params("cliente", page=1, strategy="full", incremental_since=None, rp=100)
        assert params["rp"] == "100"


class TestPaginate:
    def setup_method(self):
        self.client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
            page_size=2,
        )

    def _page(self, records, total):
        return {"registros": records, "total": str(total)}

    def test_single_page(self):
        page = self._page([{"id": "1"}, {"id": "2"}], 2)
        with patch.object(self.client, "_fetch_page", return_value=page):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert len(results) == 2

    def test_multiple_pages(self):
        pages = [
            self._page([{"id": "1"}, {"id": "2"}], 4),
            self._page([{"id": "3"}, {"id": "4"}], 4),
        ]
        with patch.object(self.client, "_fetch_page", side_effect=pages):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert len(results) == 4

    def test_empty_response_stops(self):
        page = self._page([], 0)
        with patch.object(self.client, "_fetch_page", return_value=page):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert results == []

    def test_stops_at_total(self):
        """Não busca página 3 quando total já foi atingido."""
        pages = [
            self._page([{"id": "1"}, {"id": "2"}], 3),
            self._page([{"id": "3"}], 3),
        ]
        with patch.object(self.client, "_fetch_page", side_effect=pages) as mock_fetch:
            results = list(self.client.paginate("cliente", strategy="full", page_size=2))
        assert len(results) == 3
        assert mock_fetch.call_count == 2

    def test_custom_page_size(self):
        page = self._page([{"id": "1"}], 1)
        with patch.object(self.client, "_fetch_page", return_value=page) as mock_fetch:
            list(self.client.paginate("cliente", strategy="full", page_size=999))
        call_params = mock_fetch.call_args[0][2]
        assert call_params["rp"] == "999"

    def test_total_non_numeric_continues(self):
        """Total não numérico: continua até registros vazios."""
        pages = [
            {"registros": [{"id": "1"}], "total": ""},
            {"registros": [], "total": ""},
        ]
        with patch.object(self.client, "_fetch_page", side_effect=pages):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert len(results) == 1


class TestCheckConnection:
    def test_success(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
        )
        with patch.object(client, "_fetch_page", return_value={"registros": [], "total": "0"}):
            ok, err = client.check_connection()
        assert ok is True
        assert err is None

    def test_failure(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
        )
        with patch.object(client, "_fetch_page", side_effect=httpx.ConnectError("timeout")):
            ok, err = client.check_connection()
        assert ok is False
        assert "timeout" in err
