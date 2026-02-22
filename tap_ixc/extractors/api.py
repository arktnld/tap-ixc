"""IXCClient — HTTP client para APIs IXC.

Responsabilidade única: autenticação, paginação, retry e circuit breaker.
A lógica de "qual endpoint" e "como processar" fica nas Stream classes.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, time, timedelta
from typing import Any, Iterator

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[assignment]

import httpx
import pybreaker
import stamina
import structlog

from tap_ixc.core.retry import get_circuit_breaker

log = structlog.get_logger()


def _midnight_yesterday_sp() -> str:
    tz = None
    if ZoneInfo:
        try:
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            pass
    now = datetime.now(tz) if tz else datetime.now()
    yday = now.date() - timedelta(days=1)
    dt = datetime.combine(yday, time(0, 0, 0), tzinfo=tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class IXCClient:
    """
    HTTP client para APIs IXC.

    A API usa GET com body JSON (não query string).
    Circuit breaker por endpoint — um endpoint falhando não afeta os outros.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        page_size: int = 5000,
        timeout_s: int = 60,
        max_retries: int = 5,
        backoff_factor: float = 0.5,
    ) -> None:
        encoded = base64.b64encode(token.encode()).decode()
        self._base_url = base_url.rstrip("/")
        self._auth = f"Basic {encoded}"
        self._page_size = page_size
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth,
            "Content-Type": "application/json",
            "ixcsoft": "listar",
            "Accept": "application/json",
        }

    def _build_params(
        self,
        endpoint: str,
        page: int,
        strategy: str,
        incremental_since: str | None,
        rp: int | None = None,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "page": str(page),
            "rp": str(rp if rp is not None else self._page_size),
            "sortname": f"{endpoint}.id",
            "sortorder": "desc",
        }
        if strategy == "delta":
            since = incremental_since or _midnight_yesterday_sp()
            base.update({
                "qtype": f"{endpoint}.ultima_atualizacao",
                "query": since,
                "oper": ">=",
            })
        else:
            base.update({
                "qtype": f"{endpoint}.id",
                "query": "0",
                "oper": ">=",
            })
        return base

    def _fetch_page(
        self,
        client: httpx.Client,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        breaker = get_circuit_breaker(endpoint)
        url = f"{self._base_url}/{endpoint}"
        payload = json.dumps(params)

        @stamina.retry(
            on=(httpx.HTTPError, httpx.RequestError, pybreaker.CircuitBreakerError),
            attempts=self._max_retries,
            wait_initial=self._backoff_factor,
            wait_max=self._backoff_factor * 60,
        )
        def _do() -> dict[str, Any]:
            resp = breaker.call(
                client.request,
                method="GET",
                url=url,
                content=payload,
                headers=self._headers(),
                timeout=self._timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("type") == "error":
                raise httpx.HTTPError(f"API error: {data.get('message')}")
            return data  # type: ignore[return-value]

        return _do()

    def check_connection(self) -> tuple[bool, str | None]:
        """
        Verifica se as credenciais são válidas.
        Retorna (True, None) se ok, (False, mensagem_erro) se falhar.
        """
        try:
            with httpx.Client() as client:
                params = {
                    "page": "1", "rp": "1",
                    "qtype": "cliente.id", "query": "0", "oper": ">=",
                    "sortname": "cliente.id", "sortorder": "desc",
                }
                self._fetch_page(client, "cliente", params)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def paginate(
        self,
        endpoint: str,
        strategy: str = "full",
        incremental_since: str | None = None,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Pagina um endpoint IXC, yielding um registro por vez."""
        page = 1
        total_fetched = 0
        rp = page_size if page_size is not None else self._page_size

        with httpx.Client() as client:
            while True:
                params = self._build_params(endpoint, page, strategy, incremental_since, rp)
                response = self._fetch_page(client, endpoint, params)

                records: list[dict[str, Any]] = response.get("registros", []) or []
                total_raw = response.get("total", "")
                total_api = int(total_raw) if str(total_raw).isdigit() else None

                if not records:
                    break

                for rec in records:
                    yield rec

                total_fetched += len(records)
                log.info(
                    "client.page_done",
                    endpoint=endpoint,
                    page=page,
                    fetched=total_fetched,
                    total=total_api,
                )

                if total_api is not None and total_fetched >= total_api:
                    break

                page += 1

        log.info("client.done", endpoint=endpoint, total=total_fetched)
