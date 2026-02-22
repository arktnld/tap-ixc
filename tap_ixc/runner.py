"""Runner YAML — thin wrapper sobre IXCTap usando clients.yml.

Para uso via CLI ou cron. A plataforma low-code usa IXCTap diretamente.
"""
from __future__ import annotations

import structlog

from tap_ixc.catalog import Catalog, CatalogEntry, SyncMode
from tap_ixc.config.settings import get_client
from tap_ixc.streams import STREAM_REGISTRY
from tap_ixc.tap import Destination, IXCTap, TapResult

log = structlog.get_logger()


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

    return tap.sync(destination, catalog, from_checkpoint, client_name)


def _build_catalog_from_config(cfg) -> Catalog:
    """Converte EndpointConfig do YAML em CatalogEntry."""
    entries = []
    for ep in cfg.endpoints:
        stream_cls = STREAM_REGISTRY.get(ep.name)
        if not stream_cls:
            log.warning("runner.stream_not_found", name=ep.name, available=list(STREAM_REGISTRY))
            continue
        entries.append(CatalogEntry(
            stream=stream_cls,
            destination_table=ep.name,
            sync_mode=SyncMode(ep.strategy),
            selected_fields=ep.fields,
            pk_column=ep.pk_column,
            transform_sql=ep.transform_sql,
            page_size=ep.page_size,
        ))
    return Catalog(entries)
