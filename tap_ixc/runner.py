"""Runner YAML — thin wrapper sobre IXCTap usando clients.yml.

Para uso via CLI ou cron. A plataforma low-code usa IXCTap diretamente.
"""
from __future__ import annotations

import httpx
import structlog

from tap_ixc.catalog import Catalog, CatalogEntry, SyncMode
from tap_ixc.config.settings import ClientConfig, get_client
from tap_ixc.streams import STREAM_REGISTRY
from tap_ixc.tap import Destination, IXCTap, TapResult

log = structlog.get_logger()


def _notify_webhook(url: str, client_name: str, results: list[TapResult]) -> None:
    """Dispara webhook com o resumo do run. Falha de webhook nunca quebra o sync."""
    failed = [r for r in results if r.status == "failed"]
    payload = {
        "client": client_name,
        "status": "failed" if failed else "success",
        "streams": [
            {
                "stream": r.stream,
                "status": r.status,
                "records_loaded": r.records_loaded,
                "error": r.error,
            }
            for r in results
        ],
    }
    try:
        httpx.post(url, json=payload, timeout=10)
        log.info("webhook.sent", client=client_name, status=payload["status"])
    except Exception as exc:
        log.warning("webhook.failed", client=client_name, error=str(exc))


def run(
    client_name: str,
    streams: list[str] | None = None,
    from_checkpoint: bool = False,
) -> list[TapResult]:
    """
    Roda o tap para um cliente definido no clients.yml.
    streams=None → todos os streams configurados no YAML.
    """
    cfg = get_client(client_name)
    tap = IXCTap(cfg.api)
    destination = Destination(
        postgres_dsn=cfg.postgres_dsn,
        schema=cfg.schema_name,
        duckdb_path=cfg.duckdb_resolved(),
    )

    catalog = _build_catalog_from_config(cfg)

    if streams:
        catalog = catalog.select(*streams)

    results = tap.sync(destination, catalog, from_checkpoint, client_name)

    if cfg.webhook_url:
        _notify_webhook(cfg.webhook_url, client_name, results)

    return results


def _build_catalog_from_config(cfg: ClientConfig) -> Catalog:
    """Converte EndpointConfig do YAML em CatalogEntry."""
    entries = []
    for ep in cfg.endpoints:
        stream_cls = STREAM_REGISTRY.get(ep.name)
        if not stream_cls:
            log.warning("runner.stream_not_found", name=ep.name, available=list(STREAM_REGISTRY))
            continue
        # "delta" no YAML é sinônimo de INCREMENTAL (estratégia de paginação da API)
        sync_mode = SyncMode.INCREMENTAL if ep.strategy == "delta" else SyncMode(ep.strategy)
        entries.append(CatalogEntry(
            stream=stream_cls,
            destination_table=ep.name,
            sync_mode=sync_mode,
            selected_fields=ep.fields,
            pk_column=ep.pk_column,
            transform_sql=ep.transform_sql,
            page_size=ep.page_size,
        ))
    return Catalog(entries)
