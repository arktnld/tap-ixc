# Deploy (Airflow / cron)

Cada `run` é uma carga limpa e idempotente, e o load é atômico — basta agendar.

## Por que funciona bem agendado

- **Full diário** (`strategy: full`) recria a tabela do zero — sempre o estado atual.
- **Retry seguro** — o swap é atômico; se um run falha, a tabela antiga fica intacta
  e o próximo run recarrega limpo.
- **Resiliência interna** — retry, circuit breaker, reconexão, rate limit já estão na
  lib; problemas transientes são absorvidos dentro do processo.
- **Exit code** — `tap-ixc run` sai `!= 0` se algum stream falhar → o agendador detecta.

## Cron

```cron
# todo dia às 8h
0 8 * * * cd /opt/tap-ixc && ETL_MONITOR_DSN="$ETL_MONITOR_DSN" tap-ixc run minha-empresa >> /var/log/tap-ixc.log 2>&1
```

O cron detecta falha pelo exit code `!= 0`.

## Airflow

A lib não depende de Airflow — a integração é via `runner.run()`, que retorna
`list[TapResult]` (você levanta em falha) e nunca escreve em stdout. Use a
**TaskFlow API** (Airflow 2.x e 3.x) com **uma task por stream**, para retry e
paralelismo isolados.

```python
import os
from datetime import timedelta
import pendulum

try:                                    # Airflow 3.x
    from airflow.sdk import dag, task
except ImportError:                     # Airflow 2.x
    from airflow.decorators import dag, task

CLIENT = "minha-empresa"
STREAMS = ["clientes", "contratos", "titulos"]

@dag(
    schedule="0 8 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Sao_Paulo"),
    catchup=False,                      # sempre o dado de hoje
    max_active_runs=1,                  # nunca 2 cargas simultâneas
    default_args={"retries": 3, "retry_delay": timedelta(minutes=10),
                  "execution_timeout": timedelta(hours=2)},
    tags=["ixc", "etl"],
)
def ixc_sync():
    @task
    def sync_stream(stream: str) -> dict:
        from tap_ixc.runner import run
        # staging isolado por stream (DuckDB é single-writer → tasks paralelas
        # não podem compartilhar o mesmo arquivo)
        results = run(CLIENT, [stream],
                      duckdb_path=f"/tmp/etl-staging/{CLIENT}-{stream}.duckdb")
        r = results[0]
        if r.status == "failed":
            raise RuntimeError(f"stream {r.stream} falhou: {r.error}")
        return {"stream": r.stream, "records_loaded": r.records_loaded}

    sync_stream.expand(stream=STREAMS)   # dynamic mapping: 1 task por stream

ixc_sync()
```

!!! note "Compatibilidade"
    - **Airflow 3.x**: `from airflow.sdk import dag, task` (clássico:
      `from airflow.providers.standard.operators.python import PythonOperator`).
    - **Airflow 2.x**: `from airflow.decorators import dag, task`.
    - O `try/except` no import cobre as duas versões.

!!! tip "Boas práticas em escala (lições Airflow-at-scale)"
    - **Pool para a API**: ponha as tasks de stream num pool (`@task(pool="ixc_api")`)
      com poucos slots — limita hits simultâneos na API IXC e evita rate-limit/ban de IP.
    - **Evite cron em hora redonda** (`0 8 * * *`): muitos DAGs no mesmo minuto = pico.
      Desloque o minuto por cliente (jitter determinístico).
    - **Cargas pesadas**: combine o pool com `rate_limit_sleep` no `clients.yml`
      (pausa entre páginas) para não martelar a API.
    - **Top-level barato**: mantenha `import` da lib e chamadas dentro do `@task`
      (não no topo do arquivo) — o scheduler reparseia o DAG o tempo todo.

!!! tip "Secrets e Assets"
    - Secrets: traga de **Airflow Variables/Connections** para as env vars que o
      `clients.yml` resolve (`${VAR}`), ou monte `ApiConfig`/`Destination` direto
      no task a partir da Connection (dispensa `clients.yml`).
    - Para encadear DAGs a jusante, declare a tabela como **Asset** (3.x) /
      **Dataset** (2.x): `@task(outlets=[Asset("postgres://.../clientes")])`.

Exemplo completo (mapping, secrets, compat) em
[`examples/airflow_dag.py`](https://github.com/arktnld/tap-ixc/blob/master/examples/airflow_dag.py).

!!! tip "Incremental vs full no agendamento"
    - `full` diário: simples, reconcilia deletes, recarrega tudo.
    - `delta` (incremental): mais leve (só mudanças), mas rode um `full` periódico para
      reconciliar deletes. Veja [Incremental](incremental-and-validation.md).

## Variáveis de ambiente no worker

Garanta no ambiente do cron/worker:

- `ETL_MONITOR_DSN` (e `ETL_MONITOR_SCHEMA` se não for `etl`)
- Quaisquer `${VAR}` referenciadas no `clients.yml` daquele cliente
