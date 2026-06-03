"""DAG consumidora data-aware — roda quando TODOS os streams IXC atualizam.

Prova do valor dos Assets: `schedule=(clientes & contratos & titulos)` (asset
expression AND, Airflow 3.x). Sem cron — o Airflow dispara esta DAG automaticamente
assim que os assets produzidos por `ixc_sync_<cliente>` (ver `airflow_dag.py`)
forem materializados no mesmo ciclo. Para "qualquer um", use `|` no lugar de `&`.

Exemplo de transformação: snapshot de métricas juntando os streams.
Coloque no `dags_folder` junto com `airflow_dag.py`.
"""
from __future__ import annotations

import functools
import operator
import os

import pendulum

try:  # Airflow 3.x
    from airflow.sdk import Asset, dag, task
except ImportError:  # Airflow 2.x (Datasets)
    from airflow.datasets import Dataset as Asset
    from airflow.decorators import dag, task

from tap_ixc.config.settings import load_clients

CLIENT = os.environ.get("IXC_CLIENT", "netforce")
_CFG = load_clients()[CLIENT]
_STREAMS = [ep.name for ep in _CFG.endpoints]
_ASSETS = [Asset(f"ixc://{CLIENT}/{s}") for s in _STREAMS]
_SCHEDULE = functools.reduce(operator.and_, _ASSETS)   # asset1 & asset2 & ...


@dag(
    dag_id=f"ixc_transform_{CLIENT}",
    description=f"Transforma {CLIENT} quando todos os streams atualizam (data-aware)",
    schedule=_SCHEDULE,
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Sao_Paulo"),
    catchup=False,
    tags=["ixc", "transform", CLIENT],
)
def ixc_transform():
    @task
    def build_metrics() -> dict:
        import psycopg
        counts = {}
        with psycopg.connect(_CFG.postgres_dsn, autocommit=True) as conn:
            cols = ", ".join(f"{s} bigint" for s in _STREAMS)
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS public.ixc_metrics "
                f"(snapshot_at timestamptz DEFAULT now(), {cols})"
            )
            selects = ", ".join(f"(SELECT count(*) FROM public.{s})" for s in _STREAMS)
            names = ", ".join(_STREAMS)
            conn.execute(f"INSERT INTO public.ixc_metrics ({names}) SELECT {selects}")
            for s in _STREAMS:
                counts[s] = conn.execute(f"SELECT count(*) FROM public.{s}").fetchone()[0]
        import logging
        logging.getLogger("airflow.task").info(f"ixc_metrics snapshot: {counts}")
        return counts

    build_metrics()


ixc_transform()
