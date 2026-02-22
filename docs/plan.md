# Plano de Execução — ETL Framework

## Fluxo Principal

```
python -m etl run canaa
  │
  ├─ Carrega config de clients.yml
  ├─ Valida com Pydantic
  ├─ Para cada endpoint (cliente, cliente_contrato, fn_areceber):
  │   ├─ events.start_run(client="canaa", pipeline="cliente")
  │   ├─ Consulta checkpoint → último stage completo?
  │   ├─ EXTRACT (se não checkpointado):
  │   │   ├─ httpx paginated fetch com stamina retry + pybreaker
  │   │   ├─ Grava NDJSON → DuckDB persistente
  │   │   ├─ events.emit("stage_done", stage="EXTRACT", records=15000)
  │   │   └─ checkpoint.mark_done("canaa", "cliente", "EXTRACT")
  │   ├─ VALIDATE:
  │   │   ├─ Pydantic batch validation
  │   │   ├─ Dead letter pra registros inválidos
  │   │   └─ checkpoint.mark_done(...)
  │   ├─ LOAD:
  │   │   ├─ DuckDB → Postgres (staging table → swap)
  │   │   └─ checkpoint.mark_done(...)
  │   ├─ VERIFY:
  │   │   ├─ SELECT count(*) no destino vs records extraídos
  │   │   └─ checkpoint.mark_done(...)
  │   └─ events.finish_run(records_out=15000)
  │
  └─ Webhook (se configurado)
```

## Etapas de Implementação

### Etapa 1: Core Foundation
- `core/pipeline.py` — state machine com stages
- `core/checkpoint.py` — CRUD em etl.checkpoints
- `core/events.py` — gravação em pipeline_runs/events + structlog
- `core/retry.py` — stamina + pybreaker wrapper

### Etapa 2: Config
- `config/settings.py` — Pydantic Settings + resolve env vars
- `config/clients.yml` — registro central

### Etapa 3: Extractors
- `extractors/base.py` — Protocol
- `extractors/api.py` — httpx async + circuit breaker + paginação

### Etapa 4: Loaders
- `loaders/base.py` — Protocol
- `loaders/staging.py` — NDJSON → DuckDB persistente
- `loaders/postgres.py` — DuckDB → Postgres (full/delta)

### Etapa 5: Contracts
- `core/contracts.py` — validação batch, dead letter por row

### Etapa 6: CLI + Integração
- `cli.py` — entry point com argparse/click

## Verificação

1. Unit tests: cada módulo core testável com mocks
2. Integration test: pipeline contra API real + Postgres local
3. Checkpoint test: rodar, matar no meio, retomar sem refazer stages
4. Circuit breaker test: simular API fora, verificar abertura do circuito
5. Dashboard test: verificar leitura correta de etl.pipeline_runs
6. Migration test: rodar client existente (gwg) e comparar com sistema antigo
