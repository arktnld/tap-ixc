"""IXCClient — HTTP client para APIs IXC.

Responsabilidade única: autenticação, paginação, retry e circuit breaker.
A lógica de "qual endpoint" e "como processar" fica nas Stream classes.
"""
from __future__ import annotations

import base64
import json
import math
import time
from datetime import datetime, timedelta
from typing import Any, Iterator

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[assignment]

import httpx
import stamina
import structlog

from tap_ixc.core.retry import get_circuit_breaker

log = structlog.get_logger()


class _PermanentHTTPError(Exception):
    """Erro HTTP permanente que não deve sofrer retry (4xx não transiente)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _midnight_yesterday_sp() -> str:
    tz = None
    if ZoneInfo:
        try:
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            pass
    now = datetime.now(tz) if tz else datetime.now()
    yday = now.date() - timedelta(days=1)
    dt = datetime(yday.year, yday.month, yday.day, 0, 0, 0, tzinfo=tz)
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
        wait_jitter: float = 1.0,
        session_renewal_every: int = 0,
        rate_limit_sleep: float = 0.0,
    ) -> None:
        encoded = base64.b64encode(token.encode()).decode()
        self._base_url = base_url.rstrip("/")
        self._auth = f"Basic {encoded}"
        self._page_size = page_size
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._wait_jitter = wait_jitter
        self._session_renewal_every = session_renewal_every
        self._rate_limit_sleep = rate_limit_sleep

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
            on=(
                httpx.TimeoutException,      # ConnectTimeout, ReadTimeout, WriteTimeout, PoolTimeout
                httpx.NetworkError,          # ConnectError (SSL), ReadError, WriteError
                httpx.RemoteProtocolError,   # resposta malformada, JSON inválido (wrappado abaixo)
                httpx.HTTPStatusError,       # 5xx (4xx filtrados antes de raise_for_status)
            ),
            attempts=self._max_retries,
            wait_initial=self._backoff_factor,
            wait_max=self._backoff_factor * 60,
            wait_jitter=self._wait_jitter,
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
            # Erros permanentes — não sofrem retry
            if resp.status_code in {400, 401, 403, 404}:
                raise _PermanentHTTPError(
                    resp.status_code,
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            # 429 — rate limit: respeitar Retry-After do servidor
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", self._backoff_factor * 4))
                time.sleep(retry_after)
                raise httpx.ReadTimeout(f"Rate limited (429), aguardou {retry_after:.1f}s")
            # 5xx e outros 4xx → raise_for_status → HTTPStatusError → retry
            resp.raise_for_status()
            # JSON inválido → RemoteProtocolError → retry
            try:
                data = resp.json()
            except json.JSONDecodeError as exc:
                raise httpx.RemoteProtocolError(
                    f"JSON inválido (endpoint={endpoint}): {exc}"
                ) from exc
            # Erro de negócio da API → permanente, sem retry
            if isinstance(data, dict) and data.get("type") == "error":
                raise _PermanentHTTPError(0, f"API error: {data.get('message')}")
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
        start_time = time.monotonic()

        client = httpx.Client()
        try:
            while True:
                params = self._build_params(endpoint, page, strategy, incremental_since, rp)

                # SSL reconnection: recriar sessão ao capturar ConnectError
                try:
                    response = self._fetch_page(client, endpoint, params)
                except httpx.ConnectError:
                    log.warning("client.ssl_reconnect", endpoint=endpoint, page=page)
                    client.close()
                    client = httpx.Client()
                    response = self._fetch_page(client, endpoint, params)

                # Renovação preventiva de sessão a cada N páginas
                if self._session_renewal_every and page % self._session_renewal_every == 0:
                    log.info("client.session_renewed", endpoint=endpoint, page=page)
                    client.close()
                    client = httpx.Client()

                records: list[dict[str, Any]] = response.get("registros", []) or []
                total_raw = response.get("total", "")
                total_api = int(total_raw) if str(total_raw).isdigit() else None

                if not records:
                    break

                for rec in records:
                    yield rec

                total_fetched += len(records)

                # ETA logging
                elapsed = time.monotonic() - start_time
                pct = (total_fetched / total_api * 100) if total_api else None
                eta_s = (
                    elapsed / total_fetched * (total_api - total_fetched)
                    if (total_api and total_fetched > 0 and total_fetched < total_api)
                    else None
                )
                total_pages = math.ceil(total_api / rp) if total_api else None
                log.info(
                    "client.page_done",
                    endpoint=endpoint,
                    page=f"{page}/{total_pages}" if total_pages else page,
                    fetched=total_fetched,
                    total=total_api,
                    pct=round(pct, 1) if pct is not None else None,
                    eta_s=round(eta_s) if eta_s is not None else None,
                )

                if total_api is not None and total_fetched >= total_api:
                    break

                # Rate limiting entre páginas
                if self._rate_limit_sleep > 0:
                    time.sleep(self._rate_limit_sleep)

                page += 1
        finally:
            client.close()

        log.info("client.done", endpoint=endpoint, total=total_fetched)
