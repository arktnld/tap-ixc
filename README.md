# tap-ixc

[![Docs](https://img.shields.io/badge/docs-online-008080.svg)](https://arktnld.github.io/tap-ixc/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Biblioteca Python para sincronizar dados da **API IXC Soft** para **PostgreSQL** —
com checkpointing por stage, retry, circuit breaker e observabilidade nativa.

Declare os endpoints que quer no `clients.yml`:

```yaml
minha-empresa:
  system: ixc
  schema_name: public
  postgres_dsn: "postgresql://user:pass@host/db"
  api:
    base_url: "https://sua.ixcsoft.com.br/webservice/v1"
    token: "usuario:token"
  endpoints:
    - { name: clientes, api_endpoint: cliente,     strategy: full }
    - { name: titulos,  api_endpoint: fn_areceber, strategy: delta, pk_column: id }
```

E sincronize:

```bash
tap-ixc run minha-empresa
#   ✓ clientes: 12435 registros
#   ✓ titulos: 3120 registros
```

## Por que não um script `requests`?

| No mundo real | Script cru | tap-ixc |
|---|---|---|
| API caiu na página 800/1000 | recomeça do zero | retry + circuit breaker por endpoint |
| Run diário pulou um dia | perde dados | cursor incremental retoma do último ponto |
| Falha no meio do `INSERT` | tabela em prod vazia | swap atômico (staging → COMMIT) |
| 1 registro corrompido | derruba o batch | dead letter por linha |
| "Rodou? Quanto faltou?" | nenhuma pista | tabelas `etl.*` de observabilidade |

## Instalação

```bash
pip install git+https://github.com/arktnld/tap-ixc.git
```

Desenvolvimento local:

```bash
git clone https://github.com/arktnld/tap-ixc && cd tap-ixc
pip install -e ".[dev]"
```

## Início rápido

Já instalado, do `clients.yml` ao primeiro sync:

```bash
# 1. criar a config a partir do exemplo e editar (base_url, token, postgres_dsn)
cp config/clients.yml.example config/clients.yml

# 2. apontar o banco de monitoramento e criar as tabelas
export ETL_MONITOR_DSN="postgresql://user:pass@localhost:5432/seu_db"
psql "$ETL_MONITOR_DSN" -f docs/schema.sql

# 3. validar (API + monitoramento) e rodar
tap-ixc check minha-empresa
tap-ixc run   minha-empresa       #   ✓ clientes: 12435 registros
```

> [!IMPORTANT]
> `config/clients.yml` não vem no repositório (apenas o `.example`). Se esquecer,
> a CLI avisa com o comando exato a rodar.

Para baixar só o que mudou, use `strategy: delta` no endpoint (cursor incremental
por `ultima_atualizacao`). Cada run é idempotente e o load é atômico — basta
agendar. Passo a passo completo, com explicações:
[Tutorial de 10 minutos](https://arktnld.github.io/tap-ixc/tutorial/).

## Comandos

```bash
tap-ixc check minha-empresa                  # valida credenciais + monitoramento
tap-ixc discover minha-empresa               # lista streams e modos de sync
tap-ixc run minha-empresa                    # sincroniza todos os streams
tap-ixc run minha-empresa --stream clientes  # só um
tap-ixc run minha-empresa --from-checkpoint  # retoma do último checkpoint
tap-ixc list                                 # clientes configurados
tap-ixc status --client minha-empresa        # últimos runs
```

> [!NOTE]
> `run` sai com código `!= 0` se qualquer stream falhar — seguro para cron e Airflow.

## Uso via Python

Para uso programático, sem `clients.yml`:

```python
from tap_ixc.tap import IXCTap, Destination
from tap_ixc.config.settings import ApiConfig

tap = IXCTap(ApiConfig(
    base_url="https://sua-instancia.ixcsoft.com.br/webservice/v1",
    token="usuario:token_aqui",
))

ok, err = tap.check_connection()
catalog = tap.discover()

destination = Destination(
    postgres_dsn="postgresql://user:pass@host/db",
    schema="public",
    duckdb_path="/tmp/staging.duckdb",
)
results = tap.sync(destination, catalog.select("clientes"))
# → [TapResult(stream="clientes", records_loaded=12435, status="success")]
```

## Configuração

`token`, `postgres_dsn` e `base_url` aceitam **valor literal** ou **`${VAR}`**
(variável de ambiente). Pode misturar.

```yaml
minha-empresa:
  system: ixc
  schema_name: public
  postgres_dsn: "postgresql://user:pass@localhost:5432/db"   # literal...
  duckdb_path: "/tmp/etl-staging/minha-empresa.duckdb"
  api:
    base_url: "https://minha-empresa.ixcsoft.com.br/webservice/v1"
    token: "${EMPRESA_API_TOKEN}"                            # ...ou via env
    max_retries: 3
    timeout_s: 60
  endpoints:
    - name: clientes
      api_endpoint: cliente
      strategy: full            # substitui a tabela toda
    - name: titulos
      api_endpoint: fn_areceber
      strategy: delta           # incremental por ultima_atualizacao
      pk_column: id
```

> [!TIP]
> Secrets de produção ficam melhor em `${VAR}` — não vão pro disco em texto puro.
> Para dev local, literal é mais prático.

Referência completa dos campos: [Configuração](https://arktnld.github.io/tap-ixc/configuration/).

## Streams

Três já vêm registrados — `clientes` (`cliente`), `contratos` (`cliente_contrato`)
e `titulos` (`fn_areceber`). Mas qualquer endpoint da API IXC vira um stream em
dois passos:

```python
# tap_ixc/streams/chamados.py
from tap_ixc.streams.base import Stream

class ChamadoStream(Stream):
    name = "chamados"                        # tabela destino
    api_endpoint = "su_oss_chamado"          # endpoint na API IXC
    replication_key = "ultima_atualizacao"   # None se não tiver modo delta
```

```python
# tap_ixc/streams/__init__.py
STREAM_REGISTRY = {..., ChamadoStream.name: ChamadoStream}
```

A lib cuida do resto: paginação, retry, circuit breaker, staging DuckDB, load
Postgres e checkpoint. Detalhes em [Streams](https://arktnld.github.io/tap-ixc/streams/).

## Validação e dead letter

Defina um `schema` pydantic no stream para ativar o stage `VALIDATE`: linhas
reprovadas vão para `etl.dead_letters` (com o erro) e o batch nunca falha inteiro.

```python
class ClienteSchema(BaseModel):
    id: int
    nome: str

class ClienteStream(Stream):
    name = "clientes"
    api_endpoint = "cliente"
    schema = ClienteSchema   # ativa o VALIDATE
```

> [!WARNING]
> O modo incremental só vê inserts/updates. Registros *apagados* na origem não são
> removidos do destino — rode `strategy: full` periodicamente para reconciliar.

Mais em [Incremental e validação](https://arktnld.github.io/tap-ixc/incremental-and-validation/).

## Agendamento (Airflow / cron)

```python
from tap_ixc.runner import run

results = run("minha-empresa")
if any(r.status == "failed" for r in results):
    raise RuntimeError("sync falhou")        # Airflow detecta → retry
```

Exemplo de DAG em [`examples/airflow_dag.py`](examples/airflow_dag.py); guia em
[Deploy](https://arktnld.github.io/tap-ixc/deployment/).

## Monitoramento

A lib grava em um schema PostgreSQL dedicado (`pipeline_runs`, `pipeline_events`,
`checkpoints`, `dead_letters`). Inicialize com `psql "$ETL_MONITOR_DSN" -f docs/schema.sql`
e consulte via `tap-ixc status` ou SQL. Ver [Monitoramento](https://arktnld.github.io/tap-ixc/monitoring/).

## Documentação

Documentação completa em [arktnld.github.io/tap-ixc](https://arktnld.github.io/tap-ixc/):

- [Tutorial de 10 minutos](https://arktnld.github.io/tap-ixc/tutorial/)
- [Configuração](https://arktnld.github.io/tap-ixc/configuration/) e [CLI](https://arktnld.github.io/tap-ixc/cli/)
- [API Python](https://arktnld.github.io/tap-ixc/python-api/) e [referência da API](https://arktnld.github.io/tap-ixc/api-reference/)
- [Arquitetura](https://arktnld.github.io/tap-ixc/concepts/)
- [Changelog](https://arktnld.github.io/tap-ixc/changelog/)

## Licença

MIT — veja [LICENSE](LICENSE).
