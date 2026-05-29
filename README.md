# tap-ixc

[![CI](https://github.com/arktnld/tap-ixc/actions/workflows/ci.yml/badge.svg)](https://github.com/arktnld/tap-ixc/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Sincronize dados da API IXC Soft para PostgreSQL com uma chamada — e durma tranquilo.**

`tap-ixc` extrai dados de provedores de internet que rodam **IXC Soft** (clientes, contratos, títulos — ou qualquer endpoint) e carrega no seu PostgreSQL. Diferente de um script `requests` + `INSERT`, ele já vem com tudo que faz uma carga sobreviver ao mundo real: retoma de onde parou, não derruba a tabela em produção se falhar no meio, e registra cada passo.

```python
from tap_ixc.tap import IXCTap, Destination
from tap_ixc.config.settings import ApiConfig

tap = IXCTap(ApiConfig(base_url="https://sua.ixcsoft.com.br/webservice/v1", token="user:token"))
results = tap.sync(Destination(postgres_dsn="postgresql://user:pass@host/db", schema="public", duckdb_path="/tmp/stg.duckdb"))
# → [TapResult(stream="clientes", records_loaded=12132, status="success"), ...]
```

## Por que não um script `requests`?

| Problema no mundo real | Script cru | tap-ixc |
|---|---|---|
| API caiu na página 800/1000 | recomeça do zero | **retry** + **circuit breaker** por endpoint |
| Run diário pulou um dia | perde dados | **cursor incremental** retoma do último ponto |
| Carga falha no meio do `INSERT` | tabela em prod vazia | **swap atômico** (staging → COMMIT) |
| 1 registro corrompido | derruba o batch inteiro | **dead letter** por linha, resto carrega |
| "Rodou? Quanto faltou?" | nenhuma pista | **observabilidade** nativa em tabelas Postgres |

## Recursos

- 🔄 **Sync incremental por cursor** — baixa só o que mudou desde o último run; pular um dia não perde dados
- ♻️ **Checkpoint por stage** (EXTRACT → VALIDATE → LOAD → VERIFY) — retoma sem refazer trabalho
- 🛡️ **Retry + circuit breaker por endpoint** — um endpoint instável não derruba os outros
- ⚛️ **Load atômico** — `full` (DROP+CREATE) ou `delta` (DELETE+INSERT por PK), sempre via swap transacional
- 🗑️ **Dead letter por linha** — registros inválidos vão para `etl.dead_letters`, o batch nunca falha inteiro
- 📊 **Observabilidade nativa** — `pipeline_runs`, `pipeline_events` e `checkpoints` no Postgres
- 🧩 **Qualquer endpoint IXC** vira um stream em [2 passos](#adicionar-um-stream)

## Índice

- [Instalação](#instalação)
- [Uso rápido](#uso-rápido)
- [Configuração](#configuração)
- [Streams disponíveis](#streams-disponíveis)
- [Adicionar um stream](#adicionar-um-stream)
- [Sync incremental e dead letter](#sync-incremental-e-dead-letter)
- [Agendamento (Airflow / cron)](#agendamento-airflow--cron)
- [Monitoramento](#monitoramento)
- [Licença](#licença)

## Instalação

```bash
pip install git+https://github.com/arktnld/tap-ixc.git
```

Para desenvolvimento local:

```bash
git clone https://github.com/arktnld/tap-ixc
cd tap-ixc
pip install -e ".[dev]"
```

## Uso rápido

### Via Python

```python
from tap_ixc.tap import IXCTap, Destination
from tap_ixc.config.settings import ApiConfig

tap = IXCTap(ApiConfig(
    base_url="https://sua-instancia.ixcsoft.com.br/webservice/v1",
    token="usuario:token_aqui",
))

ok, err = tap.check_connection()          # verifica credenciais
catalog = tap.discover()                  # → clientes, contratos, titulos

destination = Destination(
    postgres_dsn="postgresql://user:pass@host/db",
    schema="public",
    duckdb_path="/tmp/staging.duckdb",
)
results = tap.sync(destination, catalog.select("clientes"))
# → [TapResult(stream="clientes", records_loaded=12132, status="success")]
```

### Via CLI

```bash
export ETL_MONITOR_DSN="postgresql://user:pass@host/etl_monitor"
export MINHA_API_BASE_URL="https://..."
export MINHA_API_TOKEN="user:token"

tap-ixc run minha-empresa --stream clientes
tap-ixc run minha-empresa                    # todos os streams
tap-ixc run minha-empresa --from-checkpoint  # retoma do último checkpoint

tap-ixc check minha-empresa     # verifica credenciais
tap-ixc discover minha-empresa  # lista streams e modos de sync
tap-ixc list                    # lista clientes configurados
tap-ixc status                  # últimos 20 runs
```

> `run` sai com código `!= 0` se qualquer stream falhar — seguro para cron e Airflow.

## Configuração

```yaml
minha-empresa:
  system: ixc
  schema_name: public
  postgres_dsn: "${EMPRESA_POSTGRES_DSN}"
  duckdb_path: "/tmp/etl-staging/minha-empresa.duckdb"
  api:
    base_url: "${EMPRESA_API_BASE_URL}"
    token: "${EMPRESA_API_TOKEN}"
    max_retries: 3
    timeout_s: 60
    backoff_factor: 0.5
  endpoints:
    - name: clientes
      api_endpoint: cliente
      strategy: full
      page_size: 5000
    - name: contratos
      api_endpoint: cliente_contrato
      strategy: full
    - name: titulos
      api_endpoint: fn_areceber
      strategy: delta      # incremental por ultima_atualizacao
      pk_column: id
```

## Streams disponíveis

Estes três já vêm registrados. Todos suportam `strategy: full` e `strategy: delta`.

| Stream | Endpoint IXC |
|---|---|
| `clientes` | `cliente` |
| `contratos` | `cliente_contrato` |
| `titulos` | `fn_areceber` |

Não é uma lista fechada: qualquer endpoint exposto pela API IXC pode virar um stream.

## Adicionar um stream

Dois passos.

**1. Criar `tap_ixc/streams/<nome>.py`:**

```python
from tap_ixc.streams.base import Stream

class ChamadoStream(Stream):
    name = "chamados"                  # nome da tabela destino
    api_endpoint = "su_oss_chamado"    # endpoint na API IXC
    replication_key = "ultima_atualizacao"  # None se não tiver modo delta
```

**2. Registrar em `tap_ixc/streams/__init__.py`:**

```python
from tap_ixc.streams.chamados import ChamadoStream

STREAM_REGISTRY = {
    # ...
    ChamadoStream.name: ChamadoStream,
}
```

Pronto. A lib cuida do resto: paginação, retry, circuit breaker, staging DuckDB,
load Postgres e checkpoint. Depois é só referenciar `chamados` no `clients.yml`.

## Sync incremental e dead letter

**Incremental por cursor** — streams com `replication_key` (e `strategy: delta`) só
baixam registros alterados desde o último run bem-sucedido. O cursor é salvo em
`etl.checkpoints` e só avança após `EXTRACT + LOAD + VERIFY` completarem — se a carga
falhar no meio, o próximo run rebusca a mesma janela, sem perda. Para o backfill
histórico inicial, rode uma vez com `strategy: full`.

**Dead letter** — se um stream define um schema [pydantic](https://docs.pydantic.dev)
opcional, o stage `VALIDATE` valida cada linha; as reprovadas vão para a tabela
`etl.dead_letters` (com o erro) e o restante segue para o destino. O batch nunca
falha por causa de uma linha ruim.

```python
from pydantic import BaseModel
from tap_ixc.streams.base import Stream

class ClienteSchema(BaseModel):
    id: int
    nome: str

class ClienteStream(Stream):
    name = "clientes"
    api_endpoint = "cliente"
    replication_key = "ultima_atualizacao"
    schema = ClienteSchema   # ativa o stage VALIDATE
```

## Agendamento (Airflow / cron)

Cada run é uma carga limpa e idempotente, e o load é atômico — basta agendar.
Veja [`examples/airflow_dag.py`](examples/airflow_dag.py) para um DAG diário que
chama `runner.run()` e re-tenta a task em caso de falha.

```python
from tap_ixc.runner import run

results = run("minha-empresa")               # full fresh diário
if any(r.status == "failed" for r in results):
    raise RuntimeError("sync falhou")        # Airflow detecta → retry
```

## Monitoramento

A lib grava automaticamente em um schema PostgreSQL dedicado:

```bash
export ETL_MONITOR_DSN="postgresql://user:pass@host/db"
export ETL_MONITOR_SCHEMA="etl"  # opcional, padrão: etl

# Inicializa as tabelas
psql $ETL_MONITOR_DSN -f docs/schema.sql
```

Tabelas criadas: `pipeline_runs`, `pipeline_events`, `checkpoints`, `dead_letters`.

## Licença

MIT — veja [LICENSE](LICENSE).
