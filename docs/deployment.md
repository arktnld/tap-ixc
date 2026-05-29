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

Prefira `PythonOperator` chamando `runner.run()` — você recebe os `TapResult` na mão
(o `BashOperator` chamando a CLI também funciona, pelo exit code).

```python
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from tap_ixc.runner import run

CLIENT = "minha-empresa"

def sync_ixc(**_):
    results = run(CLIENT)                      # full fresh, idempotente
    for r in results:
        print(r.stream, r.status, r.records_loaded)
    falhas = [r for r in results if r.status == "failed"]
    if falhas:
        raise RuntimeError(f"streams falharam: {[(r.stream, r.error) for r in falhas]}")

with DAG(
    dag_id="ixc_sync_minha_empresa",
    schedule="0 8 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,                 # não reprocessa dias perdidos — sempre o dado de hoje
    max_active_runs=1,             # nunca 2 cargas simultâneas (staging DuckDB compartilhado)
    default_args={"retries": 3, "retry_delay": timedelta(minutes=10)},
    tags=["ixc", "etl"],
) as dag:
    PythonOperator(
        task_id="sync",
        python_callable=sync_ixc,
        execution_timeout=timedelta(hours=2),
    )
```

Um exemplo pronto está em
[`examples/airflow_dag.py`](https://github.com/arktnld/tap-ixc/blob/master/examples/airflow_dag.py).

!!! tip "Incremental vs full no agendamento"
    - `full` diário: simples, reconcilia deletes, recarrega tudo.
    - `delta` (incremental): mais leve (só mudanças), mas rode um `full` periódico para
      reconciliar deletes. Veja [Incremental](incremental-and-validation.md).

## Variáveis de ambiente no worker

Garanta no ambiente do cron/worker:

- `ETL_MONITOR_DSN` (e `ETL_MONITOR_SCHEMA` se não for `etl`)
- Quaisquer `${VAR}` referenciadas no `clients.yml` daquele cliente
