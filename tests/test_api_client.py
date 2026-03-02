"""Testes para IXCClient — paginação, params, check_connection."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from tap_ixc.extractors.api import IXCClient, _PermanentHTTPError, _midnight_yesterday_sp


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
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(self.client, "_fetch_page", return_value=page):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert len(results) == 2

    def test_multiple_pages(self):
        pages = [
            self._page([{"id": "1"}, {"id": "2"}], 4),
            self._page([{"id": "3"}, {"id": "4"}], 4),
        ]
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(self.client, "_fetch_page", side_effect=pages):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert len(results) == 4

    def test_empty_response_stops(self):
        page = self._page([], 0)
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(self.client, "_fetch_page", return_value=page):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert results == []

    def test_stops_at_total(self):
        """Não busca página 3 quando total já foi atingido."""
        pages = [
            self._page([{"id": "1"}, {"id": "2"}], 3),
            self._page([{"id": "3"}], 3),
        ]
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(self.client, "_fetch_page", side_effect=pages) as mock_fetch:
            results = list(self.client.paginate("cliente", strategy="full", page_size=2))
        assert len(results) == 3
        assert mock_fetch.call_count == 2

    def test_custom_page_size(self):
        page = self._page([{"id": "1"}], 1)
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(self.client, "_fetch_page", return_value=page) as mock_fetch:
            list(self.client.paginate("cliente", strategy="full", page_size=999))
        call_params = mock_fetch.call_args[0][2]
        assert call_params["rp"] == "999"

    def test_total_non_numeric_continues(self):
        """Total não numérico: continua até registros vazios."""
        pages = [
            {"registros": [{"id": "1"}], "total": ""},
            {"registros": [], "total": ""},
        ]
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(self.client, "_fetch_page", side_effect=pages):
            results = list(self.client.paginate("cliente", strategy="full"))
        assert len(results) == 1

    def test_ssl_reconnect_recreates_client(self):
        """ConnectError em _fetch_page: fechar client atual e recriar antes de retry."""
        page1 = self._page([{"id": "1"}], 1)
        calls_with_client = []

        def fetch_side_effect(http_client, endpoint, params):
            calls_with_client.append(id(http_client))
            if len(calls_with_client) == 1:
                raise httpx.ConnectError("SSL handshake failed")
            return page1

        mock_clients = [MagicMock(), MagicMock()]
        with patch.object(self.client, "_fetch_page", side_effect=fetch_side_effect):
            with patch("tap_ixc.extractors.api.httpx.Client", side_effect=mock_clients):
                results = list(self.client.paginate("cliente"))

        assert len(results) == 1
        assert len(calls_with_client) == 2
        assert calls_with_client[0] != calls_with_client[1]  # clientes diferentes


class TestCheckConnection:
    def test_success(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
        )
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(client, "_fetch_page", return_value={"registros": [], "total": "0"}):
            ok, err = client.check_connection()
        assert ok is True
        assert err is None

    def test_failure(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
        )
        with patch("tap_ixc.extractors.api.httpx.Client"), \
             patch.object(client, "_fetch_page", side_effect=httpx.ConnectError("timeout")):
            ok, err = client.check_connection()
        assert ok is False
        assert err is not None
        assert "timeout" in err


class TestFetchPage:
    """Testa _fetch_page diretamente — comportamento de erro por status code."""

    def _make_client(self, **kwargs):
        defaults = {
            "max_retries": 3,
            "backoff_factor": 0.01,  # testes rápidos
        }
        defaults.update(kwargs)
        return IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
            **defaults,
        )

    def _mock_response(self, status_code: int, json_data=None, text="", headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.headers = headers or {}
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = json.JSONDecodeError("err", "", 0)
        if status_code >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=resp
            )
        else:
            resp.raise_for_status.return_value = None
        return resp

    def test_401_raises_permanent_no_retry(self):
        client = self._make_client()
        resp = self._mock_response(401, text="Unauthorized")
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(_PermanentHTTPError) as exc_info:
                client._fetch_page(mock_http, "cliente", {})

        assert exc_info.value.status_code == 401
        assert mock_breaker.call.call_count == 1  # sem retry

    def test_403_raises_permanent_no_retry(self):
        client = self._make_client()
        resp = self._mock_response(403, text="Forbidden")
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(_PermanentHTTPError) as exc_info:
                client._fetch_page(mock_http, "cliente", {})

        assert exc_info.value.status_code == 403
        assert mock_breaker.call.call_count == 1  # sem retry

    def test_404_raises_permanent_no_retry(self):
        client = self._make_client()
        resp = self._mock_response(404, text="Not Found")
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(_PermanentHTTPError) as exc_info:
                client._fetch_page(mock_http, "cliente", {})

        assert exc_info.value.status_code == 404
        assert mock_breaker.call.call_count == 1  # sem retry

    def test_json_decode_error_retried(self):
        """JSON inválido deve ser retried (RemoteProtocolError)."""
        client = self._make_client(max_retries=2)
        resp = self._mock_response(200, json_data=None)  # json() levanta JSONDecodeError
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(httpx.RemoteProtocolError):
                client._fetch_page(mock_http, "cliente", {})

        assert mock_breaker.call.call_count == 2  # retried até max_retries

    def test_api_error_type_raises_permanent(self):
        """Resposta {'type': 'error', 'message': '...'} é permanente, sem retry."""
        client = self._make_client()
        resp = self._mock_response(200, json_data={"type": "error", "message": "endpoint inválido"})
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(_PermanentHTTPError) as exc_info:
                client._fetch_page(mock_http, "cliente", {})

        assert "endpoint inválido" in str(exc_info.value)
        assert mock_breaker.call.call_count == 1  # sem retry

    def test_500_is_retried(self):
        """5xx deve sofrer retry."""
        client = self._make_client(max_retries=2)
        resp = self._mock_response(500)
        resp.json.side_effect = None
        resp.json.return_value = {}
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(httpx.HTTPStatusError):
                client._fetch_page(mock_http, "cliente", {})

        assert mock_breaker.call.call_count == 2  # retried

    def test_circuit_breaker_error_not_retried(self):
        """CircuitBreakerError não deve sofrer retry — propaga imediatamente."""
        import pybreaker
        client = self._make_client(max_retries=3)
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.side_effect = pybreaker.CircuitBreakerError("open")

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(pybreaker.CircuitBreakerError):
                client._fetch_page(mock_http, "cliente", {})

        assert mock_breaker.call.call_count == 1  # sem retry

    def test_429_sleeps_retry_after_header(self):
        """429 com header Retry-After: deve dormir o valor indicado."""
        client = self._make_client(max_retries=2)
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {"Retry-After": "3"}
        resp.raise_for_status.return_value = None
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with patch("tap_ixc.extractors.api.time") as mock_time:
                with pytest.raises(httpx.ReadTimeout):
                    client._fetch_page(mock_http, "cliente", {})
                mock_time.sleep.assert_called_with(3.0)

    def test_429_without_retry_after_uses_default(self):
        """429 sem header Retry-After: usa backoff_factor * 4 como fallback."""
        client = self._make_client(max_retries=2, backoff_factor=0.5)
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {}
        resp.raise_for_status.return_value = None
        mock_http = MagicMock()
        mock_breaker = MagicMock()
        mock_breaker.call.return_value = resp

        with patch("tap_ixc.extractors.api.get_circuit_breaker", return_value=mock_breaker):
            with patch("tap_ixc.extractors.api.time") as mock_time:
                with pytest.raises(httpx.ReadTimeout):
                    client._fetch_page(mock_http, "cliente", {})
                mock_time.sleep.assert_called_with(2.0)  # 0.5 * 4


class TestIXCClientParams:
    def test_wait_jitter_param_accepted(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
            wait_jitter=2.0,
        )
        assert client._wait_jitter == 2.0

    def test_session_renewal_every_param_accepted(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
            session_renewal_every=50,
        )
        assert client._session_renewal_every == 50

    def test_rate_limit_sleep_param_accepted(self):
        client = IXCClient(
            base_url="https://api.example.com/webservice/v1",
            token="user:token",
            rate_limit_sleep=0.5,
        )
        assert client._rate_limit_sleep == 0.5
