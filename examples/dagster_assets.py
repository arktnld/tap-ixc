"""Exemplo Dagster — IXC → Postgres, um asset por stream.

A lib tap-ixc é agnóstica de orquestrador: aqui o mesmo `runner.run()` vira
assets Dagster (UI de linhagem + materialização ao vivo + metadata).

Rodar:
    export IXC_CLIENT=netforce
    export ETL_MONITOR_DSN="postgresql://user:pass@host/db"
    dagster dev -f examples/dagster_assets.py      # UI em http://localhost:3000

Um asset por stream configurado no clients.yml — clica "Materialize" na UI.
"""
from __future__ import annotations

import os

from dagster import Definitions, MaterializeResult, MetadataValue, asset

from tap_ixc.config.settings import get_client
from tap_ixc.runner import run

CLIENT = os.environ.get("IXC_CLIENT", "netforce")


def _make_asset(stream: str):
    @asset(name=stream, group_name=CLIENT, key_prefix=["ixc", CLIENT],
           description=f"Stream IXC '{stream}' → Postgres")
    def _sync(context) -> MaterializeResult:
        # staging isolado por stream (materializações paralelas não colidem no DuckDB)
        result = run(CLIENT, [stream],
                     duckdb_path=f"/tmp/etl-staging/{CLIENT}-{stream}.duckdb")[0]
        context.log.info(
            f"{result.stream}: extraídos={result.records_extracted} "
            f"carregados={result.records_loaded} status={result.status}"
        )
        if result.status == "failed":
            raise Exception(f"stream {result.stream} falhou: {result.error}")
        return MaterializeResult(metadata={
            "registros_carregados": MetadataValue.int(result.records_loaded),
            "registros_extraidos": MetadataValue.int(result.records_extracted),
            "status": MetadataValue.text(result.status),
        })

    return _sync


# Um asset por endpoint configurado — adiciona endpoint no clients.yml e aparece aqui.
_streams = [ep.name for ep in get_client(CLIENT).endpoints]
defs = Definitions(assets=[_make_asset(s) for s in _streams])
