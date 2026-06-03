"""DAG factory Airflow-native IXC → PostgreSQL — stages + Assets.

O Airflow É o orquestrador. Cada stream vira a cadeia

    extract >> load >> verify

e o `verify` **produz um Asset** (a tabela destino). Com isso:

- **Linhagem** na aba Assets da UI.
- **Scheduling data-aware**: um DAG a jusante (dbt, relatório) declara
  `schedule=[Asset("ixc://<cliente>/<stream>")]` e dispara automaticamente
  quando aquela tabela é atualizada — sem cron acoplado.

Handoff entre stages = staging compartilhada no Postgres (`__stg_<table>`), então
extract e load podem rodar em workers diferentes (Airflow distribuído).

Multi-tenant: um DAG por cliente do `clients.yml`. Streams enumerados no parse
(Assets precisam ser estáticos) — adicionar endpoint dispara um reparse.

Compat Airflow 2.x (Datasets) e 3.x (Assets). Coloque no `dags_folder`.
Pré-req: `pip install git+https://github.com/arktnld/tap-ixc.git`, `clients.yml`
acessível, secrets via env/Variables, e o pool: `airflow pools set ixc_api 2 "..."`.
"""
from __future__ import annotations

import pendulum

try:  # Airflow 3.x
    from airflow.sdk import Asset, dag, task, task_group
except ImportError:  # Airflow 2.x
    from airflow.datasets import Dataset as Asset
    from airflow.decorators import dag, task, task_group

from airflow.models.param import Param

from tap_ixc.config.settings import load_clients

POOL = "ixc_api"
STAGING_DIR = "/tmp/etl-staging"


def _emit_asset_meta(asset, extra: dict) -> None:
    """Anexa metadata ao evento do Asset (aparece no card da UI). Não-fatal."""
    try:
        try:  # Airflow 3.x
            from airflow.sdk import get_current_context
        except ImportError:  # Airflow 2.x
            from airflow.operators.python import get_current_context
        get_current_context()["outlet_events"][asset].extra = extra
    except Exception:
        pass


def _stream_group(client_name: str, stream: str):
    """Cadeia extract>>load>>verify para um stream; verify produz o Asset."""
    asset = Asset(f"ixc://{client_name}/{stream}")

    @task_group(group_id=stream)
    def etl():
        @task.short_circuit
        def gate(**context) -> bool:
            # interruptor por stream (param run_<stream> no trigger manual); default True.
            return bool((context.get("params") or {}).get(f"run_{stream}", True))

        @task(pool=POOL)
        def extract() -> dict:
            from tap_ixc import stages
            return stages.extract(client_name, stream,
                                  duckdb_path=f"{STAGING_DIR}/{client_name}-{stream}.duckdb")

        @task
        def load(ex: dict) -> dict:
            from tap_ixc import stages
            if ex["empty"]:
                return {"stream": ex["stream"], "records_loaded": 0}
            return stages.load(client_name, ex["stream"])

        @task(outlets=[asset])
        def verify(ex: dict, ld: dict) -> dict:
            from tap_ixc import stages
            if ex["empty"]:
                _emit_asset_meta(asset, {"records_loaded": 0, "status": "empty"})
                return {"stream": ex["stream"], "ok": True, "records_loaded": 0}
            result = stages.verify(client_name, ex["stream"],
                                  extracted=ex["records_extracted"],
                                  loaded=ld["records_loaded"], new_cursor=ex["new_cursor"])
            _emit_asset_meta(asset, {
                "records_loaded": ld["records_loaded"],
                "records_extracted": ex["records_extracted"],
                "status": "success",
            })
            return result

        ex = extract()
        gate() >> ex          # interruptor: pula o stream se desmarcado no trigger
        ld = load(ex)
        verify(ex, ld)

    return etl


def build_ixc_dag(client_name: str):
    cfg = load_clients()[client_name]
    streams = [ep.name for ep in cfg.endpoints]
    minute = sum(ord(c) for c in client_name) % 60   # jitter por cliente

    @dag(
        dag_id=f"ixc_sync_{client_name}",
        description=f"IXC {client_name} — extract>>load>>verify por stream, produz Assets",
        schedule=f"{minute} 8 * * *",
        start_date=pendulum.datetime(2026, 1, 1, tz="America/Sao_Paulo"),
        catchup=False,
        max_active_runs=1,
        default_args={"owner": "data", "retries": 3, "retry_exponential_backoff": True},
        params={f"run_{s}": Param(True, type="boolean", title=f"Rodar {s}") for s in streams},
        tags=["ixc", "etl", client_name],
    )
    def _factory():
        for stream in streams:
            _stream_group(client_name, stream)()

    return _factory()


# Um DAG por cliente configurado.
for _client in load_clients():
    globals()[f"ixc_sync_{_client}"] = build_ixc_dag(_client)
