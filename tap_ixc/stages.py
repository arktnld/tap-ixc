"""Primitivos de stage para orquestração externa (Airflow-native).

Diferente de `runner.run()` / `IXCTap.sync()` (pipeline inteiro numa chamada),
aqui cada stage é uma função independente que o ORQUESTRADOR encadeia:

    extract(client, stream) >> load(client, stream) >> verify(...)

O handoff entre stages é a **staging compartilhada no Postgres** (`__stg_<table>`),
então extract e load podem rodar em workers diferentes (Airflow distribuído).
O orquestrador cuida de retry/estado por stage; o cursor incremental só avança
no `verify` (após sucesso).
"""
from __future__ import annotations

from typing import Any

import structlog

from tap_ixc.catalog import CatalogEntry, SyncMode
from tap_ixc.config.settings import Settings, get_client
from tap_ixc.core.checkpoint import Checkpoint
from tap_ixc.extractors.api import IXCClient
from tap_ixc.loaders.postgres import PostgresLoader
from tap_ixc.loaders.staging import StagingLoader
from tap_ixc.streams import STREAM_REGISTRY
from tap_ixc.tap import _advance_cursor

log = structlog.get_logger()


def _entry(cfg, stream: str) -> CatalogEntry:
    ep = next((e for e in cfg.endpoints if e.name == stream), None)
    if ep is None:
        raise ValueError(f"Stream '{stream}' não configurado para este cliente.")
    stream_cls = STREAM_REGISTRY.get(stream)
    if stream_cls is None:
        raise ValueError(f"Stream '{stream}' sem classe no STREAM_REGISTRY.")
    sync_mode = SyncMode.INCREMENTAL if ep.strategy == "delta" else SyncMode(ep.strategy)
    return CatalogEntry(
        stream=stream_cls, destination_table=ep.name, sync_mode=sync_mode,
        selected_fields=ep.fields, pk_column=ep.pk_column,
        transform_sql=ep.transform_sql, page_size=ep.page_size,
    )


def _client(cfg) -> IXCClient:
    a = cfg.api
    return IXCClient(
        base_url=a.base_url, token=a.token, max_retries=a.max_retries,
        timeout_s=a.timeout_s, backoff_factor=a.backoff_factor, wait_jitter=a.wait_jitter,
        session_renewal_every=a.session_renewal_every, rate_limit_sleep=a.rate_limit_sleep,
    )


def _pg(cfg, entry: CatalogEntry, duckdb_path: str) -> PostgresLoader:
    return PostgresLoader(
        duckdb_path=duckdb_path, pg_dsn=cfg.postgres_dsn, schema=cfg.schema_name,
        table=entry.destination_table, strategy=entry.sync_mode.value, pk_column=entry.pk_column,
    )


def _checkpoint() -> Checkpoint:
    s = Settings()
    return Checkpoint(s.monitor_dsn, schema=s.monitor_schema)


def extract(client_name: str, stream: str, *, duckdb_path: str) -> dict[str, Any]:
    """API → staging compartilhada no Postgres (`__stg_<table>`).

    Retorna ``{stream, records_extracted, new_cursor, empty}`` — passe via XCom
    para os stages seguintes.
    """
    cfg = get_client(client_name)
    entry = _entry(cfg, stream)
    stream_obj = entry.stream()
    rep_key = stream_obj.replication_key

    since: str | None = None
    if entry.sync_mode == SyncMode.INCREMENTAL and rep_key:
        cp = _checkpoint().get_last(client_name, entry.destination_table)
        if cp and cp.get("metadata"):
            since = cp["metadata"].get("replication_key_value")

    cursor: dict[str, str | None] = {"v": since}

    def tracked(it):
        for rec in it:
            if rep_key:
                cursor["v"] = _advance_cursor(cursor["v"], rec.get(rep_key))
            yield rec

    staging = StagingLoader(
        duckdb_path=duckdb_path, table=entry.destination_table,
        fields=entry.selected_fields, transform_sql=entry.transform_sql,
    )
    records = stream_obj.get_records(_client(cfg), entry.sync_mode, since=since,
                                     page_size=entry.page_size)
    _, total = staging.load(tracked(records))

    if total > 0:
        _pg(cfg, entry, duckdb_path).stage()   # DuckDB local → __stg_ (compartilhada)

    return {
        "stream": stream, "records_extracted": total,
        "new_cursor": cursor["v"], "empty": total == 0,
    }


def load(client_name: str, stream: str, *, duckdb_path: str = "/tmp/_swap.duckdb") -> dict[str, Any]:
    """Staging do Postgres (`__stg_<table>`) → tabela final (swap atômico).

    Só fala com o Postgres → roda em qualquer worker. `duckdb_path` é ignorado
    (swap usa DuckDB em memória).
    """
    cfg = get_client(client_name)
    entry = _entry(cfg, stream)
    loaded = _pg(cfg, entry, duckdb_path).swap()
    return {"stream": stream, "records_loaded": loaded}


def verify(client_name: str, stream: str, *, extracted: int, loaded: int,
           new_cursor: str | None = None) -> dict[str, Any]:
    """Confere a contagem e avança o cursor incremental (só após sucesso)."""
    if extracted > 0 and loaded == 0:
        raise RuntimeError(f"{stream}: verificação falhou ({extracted} extraídos, 0 carregados)")
    if extracted != loaded:
        raise RuntimeError(f"{stream}: contagem divergente ({extracted} extraídos, {loaded} carregados)")

    if new_cursor is not None:
        cfg = get_client(client_name)
        entry = _entry(cfg, stream)
        _checkpoint().mark_done(
            client_name, entry.destination_table, "VERIFY",
            metadata={"replication_key_value": new_cursor},
        )
    log.info("stage.verify_ok", stream=stream, records=loaded)
    return {"stream": stream, "ok": True, "records_loaded": loaded}
