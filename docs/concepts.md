# Arquitetura

## Visão geral

```
IXCTap.sync()
  └─ para cada CatalogEntry → PipelineRun.execute():
       EXTRACT  → Stream.get_records() → IXCClient.paginate() → StagingLoader (NDJSON→DuckDB)
       VALIDATE → contracts.validate_batch() → dead letter por linha   (só se Stream.schema)
       LOAD     → PostgresLoader (DuckDB→Postgres, full/delta, swap atômico)
       VERIFY   → confere contagem carregada
  └─ TapResult por stream
```

Camadas, com responsabilidade única:

| Camada | Módulo | Responsabilidade |
|---|---|---|
| Orquestração | `tap.py` | `IXCTap` — check, discover, sync |
| Catálogo | `catalog.py` | `Catalog`, `CatalogEntry`, `SyncMode` |
| Stream | `streams/` | Metadados (name, endpoint, replication_key, schema) |
| HTTP | `extractors/api.py` | Paginação, retry, circuit breaker |
| State machine | `core/pipeline.py` | Stages + checkpoint por stage |
| Loaders | `loaders/` | Staging (DuckDB) e destino (Postgres) |
| Observabilidade | `core/events.py`, `core/checkpoint.py` | Tabelas `etl.*` |
| Config | `config/settings.py` | Pydantic Settings + `clients.yml` |

## State machine por stage

Os 4 stages rodam em ordem e **cada um é checkpointado individualmente** na tabela
`etl.checkpoints` (PK `client, pipeline`):

```
EXTRACT → VALIDATE → LOAD → VERIFY
```

- `EXTRACT` — pagina a API e grava NDJSON → DuckDB persistente.
- `VALIDATE` — só roda se o `Stream` define `schema`; valida cada linha e manda as
  reprovadas para dead letter. Sem schema, é pulado.
- `LOAD` — DuckDB → Postgres (`full` ou `delta`), via swap transacional.
- `VERIFY` — confere que a contagem carregada bate com o esperado.

### Retomada (`--from-checkpoint`)

Um stage só é marcado **depois** de concluir com sucesso. Se `LOAD` falha, o
checkpoint fica em `EXTRACT` → na próxima execução com `--from-checkpoint`, `EXTRACT`
é pulado e `LOAD` retoma — sem rebaixar os dados.

## Cursor incremental

Streams com `replication_key` (ex: `ultima_atualizacao`) e `strategy: delta` só
buscam o que mudou. O **último valor do cursor** é salvo em `etl.checkpoints.metadata`
e usado como filtro (`ultima_atualizacao >= cursor`) na chamada seguinte.

- O cursor **só avança após `EXTRACT + LOAD + VERIFY`** completarem. Se `LOAD` falha,
  o cursor não anda → a janela é rebuscada no próximo run (sem perda).
- Pular um dia **não perde dados** (diferente de filtrar por "ontem" fixo).
- O boundary é inclusivo (`>=`); como o `delta` é idempotente (DELETE+INSERT por PK),
  re-buscar a linha de fronteira é inofensivo.

!!! warning "Backfill e deletes"
    - O **primeiro** carregamento histórico deve usar `strategy: full`.
    - O incremental só vê inserts/updates. Para reconciliar **deletes** na origem,
      rode `strategy: full` periodicamente.

## Load atômico

`PostgresLoader` cria uma staging remota, e dentro de uma transação faz o swap:

- `full` → `DROP TABLE` + `CREATE TABLE AS SELECT`
- `delta` → `DELETE ... WHERE pk IN staging` + `INSERT`

Se falhar no meio, `ROLLBACK` mantém a tabela antiga intacta — nunca fica vazia/parcial.

### Schema evolution

No `delta`, se a origem ganhou uma coluna nova, ela é adicionada no destino via
`ALTER TABLE ADD COLUMN` (tipo inferido DuckDB→Postgres) e o `INSERT` é por nome de
coluna — resiliente a colunas novas, reordenadas ou ausentes.

## Resiliência HTTP

- **Retry** (stamina) com backoff exponencial + jitter em erros transientes
  (timeout, rede, 5xx, JSON inválido).
- **Erros permanentes** — qualquer 4xx (exceto 429) e erro de negócio da API não
  sofrem retry.
- **429** — respeita `Retry-After` do servidor.
- **Circuit breaker por endpoint** (pybreaker): abre após 5 falhas, reset em 60s.
  Um endpoint instável **não** afeta os outros.

## Dead letter por linha

`contracts.sanitize()` roda sempre (datas inválidas tipo `0000-00-00` viram `null`,
strings vazias viram `null`). Quando o `Stream` define `schema` (pydantic),
`validate_batch()` separa válidas de reprovadas — as reprovadas vão para
`etl.dead_letters` com o erro, e **o batch nunca falha inteiro**.

## DuckDB persistente

O staging usa DuckDB **em arquivo** (nunca `:memory:`), com WAL — sobrevive a crash e
permite retomar o `LOAD` sem re-extrair.

## Inspiração: Singer SDK

Herdamos do [Singer SDK](https://sdk.meltano.com): `Tap`, `Stream`, `discover()`,
`Catalog`, `SyncMode`, `replication_key`, `primary_keys`.

Onde divergimos de propósito:

- **Destino explícito** (`Destination`) em vez de `Target` solto.
- **Checkpoint por stage no Postgres**, não arquivo de state — auditável e distribuído.
- **`TapResult`** como retorno (uso programático), em vez de escrever em stdout.
- **`IXCClient` separado do `Stream`** — HTTP e metadados desacoplados.
