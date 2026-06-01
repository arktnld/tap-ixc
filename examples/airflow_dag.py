"""DAG Airflow — sync diário IXC → PostgreSQL (TaskFlow, task por stream).

Padrões 2026:
- TaskFlow API (`@dag`/`@task`), compatível com Airflow 2.x e 3.x.
- Uma task por stream via dynamic task mapping (`.expand`): retry e paralelismo
  isolados — um stream falhar não re-roda os outros.
- Staging DuckDB isolado por stream (DuckDB é single-writer; tasks paralelas não
  podem compartilhar o mesmo arquivo).
- Secrets vêm de Airflow Variables (ponte para as env vars que o `clients.yml`
  resolve). Em produção, prefira Airflow Connections / um secrets backend.
- `catchup=False` + `max_active_runs=1`: sempre o dado de hoje, sem sobreposição.

Pré-requisito no worker: `pip install git+https://github.com/arktnld/tap-ixc.git`
e `config/clients.yml` acessível (ou use a API Python direto — ver nota no fim).
"""
from __future__ import annotations

import os
from datetime import timedelta

import pendulum

# Compat de imports: Airflow 3.x usa airflow.sdk; 2.x usa airflow.decorators.
try:  # Airflow 3.x
    from airflow.sdk import dag, task
except ImportError:  # Airflow 2.x
    from airflow.decorators import dag, task

CLIENT = "gwg"
# Streams a sincronizar. Em produção pode vir de um Airflow Variable / DAG param.
STREAMS = ["clientes", "contratos", "titulos"]

# Env vars que o clients.yml (${VAR}) precisa resolver — buscadas em Airflow Variables.
_SECRET_VARS = ["GWG_API_BASE_URL", "GWG_API_TOKEN", "GWG_POSTGRES_DSN", "ETL_MONITOR_DSN"]


def _hydrate_secrets() -> None:
    """Copia secrets de Airflow Variables para env (cada task roda em processo próprio)."""
    try:
        from airflow.sdk import Variable          # Airflow 3.x
    except ImportError:
        from airflow.models import Variable        # Airflow 2.x
    for key in _SECRET_VARS:
        val = Variable.get(key, default_var=None)
        if val:
            os.environ.setdefault(key, val)


# Schedule com jitter determinístico por cliente — evita pico de carga quando
# muitos DAGs rodam na mesma hora redonda (lição Airflow-at-scale da Shopify).
# Minuto = hash(cliente) % 60; troque por um cron fixo se preferir.
_MIN = sum(ord(c) for c in CLIENT) % 60


@dag(
    dag_id="ixc_sync_gwg",
    description="Sync diário IXC (um task por stream) → Postgres",
    schedule=f"{_MIN} 8 * * *",           # ~8h, minuto deslocado por cliente
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Sao_Paulo"),
    catchup=False,
    max_active_runs=1,                    # nunca 2 cargas simultâneas
    default_args={
        "owner": "data",
        "retries": 3,
        "retry_delay": timedelta(minutes=10),
        "retry_exponential_backoff": True,
        "execution_timeout": timedelta(hours=2),
    },
    tags=["ixc", "etl"],
)
def ixc_sync():
    # pool="ixc_api": cap de streams batendo na API IXC ao mesmo tempo.
    # Crie o pool no Airflow (ex: 2 slots) p/ evitar rate-limit / ban de IP.
    @task(pool="ixc_api")
    def sync_stream(stream: str) -> dict:
        """Sincroniza UM stream. Levanta se falhar → Airflow re-tenta só este."""
        from tap_ixc.runner import run

        _hydrate_secrets()
        # Staging isolado por stream (tasks paralelas não compartilham DuckDB).
        duckdb_path = f"/tmp/etl-staging/{CLIENT}-{stream}.duckdb"
        results = run(CLIENT, [stream], duckdb_path=duckdb_path)

        r = results[0]
        print(f"{r.stream}: extraídos={r.records_extracted} "
              f"carregados={r.records_loaded} status={r.status}")
        if r.status == "failed":
            raise RuntimeError(f"stream {r.stream} falhou: {r.error}")
        return {"stream": r.stream, "records_loaded": r.records_loaded}

    # Dynamic task mapping: uma instância de task por stream, em paralelo.
    sync_stream.expand(stream=STREAMS)


ixc_sync()

# ─────────────────────────────────────────────────────────────────────────────
# Alternativa sem clients.yml (config 100% no Airflow): dentro do task, monte
# ApiConfig/Destination com valores de Variables/Connections e chame IXCTap direto:
#
#     from tap_ixc.tap import IXCTap, Destination
#     from tap_ixc.config.settings import ApiConfig
#     tap = IXCTap(ApiConfig(base_url=..., token=...))
#     tap.sync(Destination(postgres_dsn=..., schema=..., duckdb_path=...),
#              tap.discover().select(stream))
#
# Assets (Airflow 3.x) / Datasets (2.x): declare a tabela destino como saída para
# disparar DAGs a jusante — `@task(outlets=[Asset("postgres://.../clientes")])`.
# ─────────────────────────────────────────────────────────────────────────────
