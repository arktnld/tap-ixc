"""DAG Airflow — sync diário IXC → Postgres.

Roda todo dia às 8h, carga full do zero (clientes, contratos, titulos).
Resiliência transiente (retry HTTP, circuit breaker, rate limit) é interna ao tap.
Falhas de processo/stream sobem como exceção → Airflow re-tenta a task.

NÃO usa --from-checkpoint: cada run é uma carga limpa. O load no Postgres é
atômico (staging remota + swap em transação), então retry após crash não deixa
estado pela metade — a tabela antiga permanece até o swap commitar.

Pré-requisito: `pip install git+https://github.com/arktnld/tap-ixc.git`
e as env vars do cliente (ex.: GWG_POSTGRES_DSN, GWG_API_*) disponíveis no worker.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from tap_ixc.runner import run

CLIENT = "gwg"


def sync_ixc(**_context) -> None:
    """Sincroniza todos os streams do cliente. Levanta se algum falhar."""
    results = run(CLIENT)  # full fresh, sem checkpoint

    for r in results:
        print(f"{r.stream}: extraídos={r.records_extracted} "
              f"carregados={r.records_loaded} status={r.status}")

    failed = [r for r in results if r.status == "failed"]
    if failed:
        # sobe exceção → task FAILED → Airflow re-tenta (ver retries abaixo)
        detail = ", ".join(f"{r.stream}: {r.error}" for r in failed)
        raise RuntimeError(f"streams falharam: {detail}")


default_args = {
    "owner": "data",
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
}

with DAG(
    dag_id="ixc_sync_gwg",
    description="Sync diário IXC (clientes, contratos, titulos) → Postgres",
    schedule="0 8 * * *",          # todo dia às 8h
    start_date=datetime(2026, 1, 1),
    catchup=False,                  # não reprocessa dias perdidos — sempre o dado de hoje
    max_active_runs=1,              # nunca 2 cargas simultâneas (DuckDB staging compartilhado)
    default_args=default_args,
    tags=["ixc", "etl"],
) as dag:
    PythonOperator(
        task_id="sync",
        python_callable=sync_ixc,
        execution_timeout=timedelta(hours=2),
    )
