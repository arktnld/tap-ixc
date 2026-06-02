"""DAG factory Airflow-native IXC → PostgreSQL — stages como tasks.

O Airflow É o orquestrador: cada stream vira a cadeia

    extract >> load >> verify

- **extract**: API → staging compartilhada no Postgres (`__stg_<table>`)
- **load**:    `__stg_` → tabela final (swap atômico) — roda em qualquer worker
- **verify**:  confere contagem e avança o cursor incremental (só após sucesso)

Retry, estado e observabilidade por stage são do Airflow. A staging viver no
Postgres (não em disco local) permite extract e load em workers diferentes
(Airflow distribuído: Celery/Kubernetes).

Padrão multi-tenant: um DAG por cliente do `clients.yml`. Adiciona cliente → novo
DAG; adiciona endpoint → novo stream mapeado (em runtime, sem editar nada aqui).

Compatível com Airflow 2.x e 3.x. Coloque no `dags_folder`.
Pré-requisito: `pip install git+https://github.com/arktnld/tap-ixc.git`,
`clients.yml` acessível, secrets via env/Airflow Variables, e o pool `ixc_api`
(`airflow pools set ixc_api 2 "..."`).
"""
from __future__ import annotations

import pendulum

try:  # Airflow 3.x
    from airflow.sdk import dag, task, task_group
except ImportError:  # Airflow 2.x
    from airflow.decorators import dag, task, task_group

from tap_ixc.config.settings import load_clients

POOL = "ixc_api"
STAGING_DIR = "/tmp/etl-staging"


def build_ixc_dag(client_name: str):
    minute = sum(ord(c) for c in client_name) % 60   # jitter por cliente

    @dag(
        dag_id=f"ixc_sync_{client_name}",
        description=f"IXC {client_name} — extract>>load>>verify por stream",
        schedule=f"{minute} 8 * * *",
        start_date=pendulum.datetime(2026, 1, 1, tz="America/Sao_Paulo"),
        catchup=False,
        max_active_runs=1,
        default_args={"owner": "data", "retries": 3, "retry_exponential_backoff": True},
        params={"streams": None},
        tags=["ixc", "etl", client_name],
    )
    def _factory():
        @task
        def list_streams(**ctx) -> list[str]:
            from tap_ixc.config.settings import get_client
            configured = [ep.name for ep in get_client(client_name).endpoints]
            chosen = (ctx.get("params") or {}).get("streams")
            return [s for s in chosen if s in configured] if chosen else configured

        @task_group(group_id="stream")
        def stream_etl(stream: str):
            @task(pool=POOL)                 # cap de concorrência na API IXC
            def extract(stream: str) -> dict:
                from tap_ixc import stages
                return stages.extract(client_name, stream,
                                      duckdb_path=f"{STAGING_DIR}/{client_name}-{stream}.duckdb")

            @task
            def load(ex: dict) -> dict:
                from tap_ixc import stages
                if ex["empty"]:
                    return {"stream": ex["stream"], "records_loaded": 0}
                return stages.load(client_name, ex["stream"])

            @task
            def verify(ex: dict, ld: dict) -> dict:
                from tap_ixc import stages
                if ex["empty"]:
                    return {"stream": ex["stream"], "ok": True, "records_loaded": 0}
                return stages.verify(client_name, ex["stream"],
                                    extracted=ex["records_extracted"],
                                    loaded=ld["records_loaded"],
                                    new_cursor=ex["new_cursor"])

            ex = extract(stream)
            ld = load(ex)
            verify(ex, ld)

        stream_etl.expand(stream=list_streams())

    return _factory()


# Um DAG por cliente (parse-time barato: só enumera clientes).
for _client in load_clients():
    globals()[f"ixc_sync_{_client}"] = build_ixc_dag(_client)
