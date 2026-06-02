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

Há **duas formas**, dependendo de quem orquestra:

### Airflow-native — stages como tasks (recomendado)

O Airflow é o orquestrador: cada stream vira a cadeia **`extract >> load >> verify`**,
e o `verify` **produz um Asset** (a tabela destino). A lib expõe os stages em
`tap_ixc.stages`. O handoff entre tasks é a **staging compartilhada no Postgres**
(`__stg_<table>`), então extract e load podem rodar em **workers diferentes**
(Celery/Kubernetes). Retry e estado são por stage.

```python
import pendulum
try:                                          # Airflow 3.x
    from airflow.sdk import Asset, dag, task, task_group
except ImportError:                           # Airflow 2.x (Datasets)
    from airflow.datasets import Dataset as Asset
    from airflow.decorators import dag, task, task_group

from tap_ixc.config.settings import load_clients

CLIENT = "minha-empresa"

@dag(schedule="7 8 * * *", start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
     catchup=False, max_active_runs=1, tags=["ixc", "etl"])
def ixc_sync():
    for stream in [ep.name for ep in load_clients()[CLIENT].endpoints]:

        @task_group(group_id=stream)
        def stream_etl(stream=stream):
            @task(pool="ixc_api")
            def extract():
                from tap_ixc import stages
                return stages.extract(CLIENT, stream,
                                      duckdb_path=f"/tmp/etl-staging/{CLIENT}-{stream}.duckdb")
            @task
            def load(ex):
                from tap_ixc import stages
                return {"stream": ex["stream"], "records_loaded": 0} if ex["empty"] \
                       else stages.load(CLIENT, ex["stream"])
            @task(outlets=[Asset(f"ixc://{CLIENT}/{stream}")])   # ← produz o Asset
            def verify(ex, ld):
                from tap_ixc import stages
                if ex["empty"]:
                    return {"ok": True}
                return stages.verify(CLIENT, ex["stream"], extracted=ex["records_extracted"],
                                     loaded=ld["records_loaded"], new_cursor=ex["new_cursor"])
            ex = extract(); ld = load(ex); verify(ex, ld)

        stream_etl()

ixc_sync()
```

O `verify` também anexa **metadata** ao evento do Asset (`records_loaded`,
`status`) via `outlet_events` — aparece no card do Asset na UI (quantos registros
na última materialização). Veja `examples/airflow_dag.py`.

**Scheduling data-aware**: um DAG a jusante dispara sozinho quando a tabela atualiza:

```python
@dag(schedule=[Asset("ixc://minha-empresa/clientes")], catchup=False)   # sem cron
def transforma_clientes():
    ...   # roda quando o stream clientes termina
```

O cursor incremental só avança no `verify` (após sucesso). Exemplo completo, com
factory multi-cliente, em
[`examples/airflow_dag.py`](https://github.com/arktnld/tap-ixc/blob/master/examples/airflow_dag.py).

### Lib-orquestra — uma task por stream (mais simples)

Se preferir o pipeline inteiro numa task (staging local, sem Postgres compartilhado;
mesmo código de `cron`), use `runner.run()`:

```python
@task(pool="ixc_api")
def sync_stream(stream: str):
    from tap_ixc.runner import run
    r = run(CLIENT, [stream], duckdb_path=f"/tmp/etl-staging/{CLIENT}-{stream}.duckdb")[0]
    if r.status == "failed":
        raise RuntimeError(r.error)
    return {"stream": r.stream, "records_loaded": r.records_loaded}
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
