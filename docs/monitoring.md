# Monitoramento

A lib grava automaticamente em um schema PostgreSQL dedicado (default `etl`),
separado do destino dos dados.

## Setup

```bash
export ETL_MONITOR_DSN="postgresql://user:pass@host/db"
export ETL_MONITOR_SCHEMA="etl"   # opcional, padrão: etl
psql "$ETL_MONITOR_DSN" -f docs/schema.sql
```

## Tabelas

### `etl.pipeline_runs`

Um registro por execução de stream.

| Coluna | Descrição |
|---|---|
| `id` | PK serial |
| `client`, `system`, `pipeline` | quem rodou (pipeline = nome do stream) |
| `status` | `RUNNING` → `SUCCESS` / `FAILED` |
| `stage` | último stage alcançado |
| `started_at`, `finished_at`, `duration_s` | tempos |
| `records_in`, `records_out` | extraídos / carregados |
| `error` | mensagem em caso de falha |
| `metadata` | JSONB livre |

### `etl.checkpoints`

Estado por stage (PK `client, pipeline`). Guarda o último stage concluído e, para
streams incrementais, o **cursor** em `metadata.replication_key_value`.

### `etl.pipeline_events`

Eventos granulares (`stage_start`, `stage_done`, `stage_skipped`, ...) ligados a um
`run_id`.

### `etl.dead_letters`

Linhas reprovadas na validação (ver [Validação](incremental-and-validation.md)).

| Coluna | Descrição |
|---|---|
| `run_id` | FK para `pipeline_runs` |
| `stream` | stream de origem |
| `record` | JSONB com a linha original |
| `errors` | JSONB com o detalhe do erro |

## Consultas úteis

Últimos runs (também via `tap-ixc status`):

```sql
SELECT client, pipeline, status, duration_s, records_out, started_at
FROM etl.pipeline_runs
ORDER BY started_at DESC
LIMIT 20;
```

Runs que falharam hoje:

```sql
SELECT client, pipeline, error, started_at
FROM etl.pipeline_runs
WHERE status = 'FAILED' AND started_at::date = current_date;
```

Volume por stream ao longo do tempo (detecta anomalia):

```sql
SELECT pipeline, started_at::date AS dia, max(records_out) AS registros
FROM etl.pipeline_runs
WHERE status = 'SUCCESS'
GROUP BY pipeline, dia
ORDER BY dia DESC;
```

## Webhook

Defina `webhook_url` no cliente (`clients.yml`) para receber um POST com o resumo ao
fim de cada `run` (via `runner`/CLI):

```json
{
  "client": "minha-empresa",
  "status": "failed",
  "streams": [
    {"stream": "clientes", "status": "success", "records_loaded": 12435, "error": null},
    {"stream": "titulos",  "status": "failed",  "records_loaded": 0, "error": "..."}
  ]
}
```

A falha de webhook é **não-fatal** (não derruba o sync).
