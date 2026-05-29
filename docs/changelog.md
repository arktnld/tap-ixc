# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- **Sync incremental por cursor** — lê/grava o último `ultima_atualizacao` no
  checkpoint; só avança após `EXTRACT + LOAD + VERIFY`. Pular um run não perde dados.
- **Stage `VALIDATE` + dead letter** — `Stream.schema` (pydantic) opcional; linhas
  reprovadas vão para `etl.dead_letters`, o batch não falha.
- **Schema evolution no `delta`** — coluna nova na origem é adicionada no destino
  (`ALTER TABLE ADD COLUMN`), `INSERT` por nome de coluna.
- **Webhook de notificação** — `webhook_url` do cliente recebe o resumo ao fim do run.
- **Verificação de contagem no `VERIFY`** — falha se o carregado diverge do esperado.
- **Site de documentação** (MkDocs Material) publicado no GitHub Pages.
- **Exemplo de DAG Airflow** em `examples/`.

### Corrigido
- **Extração vazia** (incremental sem mudanças) virava erro — agora é no-op de sucesso.
- **`--from-checkpoint`** dava falso "contagem divergente" no resume — corrigido.
- **CLI exit code** — `run` agora sai `!= 0` quando algum stream falha (Airflow/cron).
- **Mensagens de erro humanizadas** em todos os comandos (config faltando, env var
  ausente, YAML inválido, monitor fora, schema ausente) — sem traceback cru.
- **Estratégia `delta` no YAML** mapeada corretamente para `SyncMode.INCREMENTAL`.

### Segurança
- **Validação de identificadores** (tabela/schema/pk vindos de config) contra injeção
  de SQL.
- **4xx permanente abrangente** — qualquer 4xx (exceto 429) não sofre retry inútil.

### Removido
- Campos de config mortos (`schema_cls`, `timeout_s` por endpoint).

## [0.1.0]

### Adicionado
- Núcleo: `IXCTap` (check / discover / sync), state machine por stage
  (EXTRACT → LOAD → VERIFY), checkpoint no Postgres.
- `IXCClient` com paginação, retry (stamina), circuit breaker por endpoint
  (pybreaker), reconexão SSL e rate limiting.
- Loaders: staging NDJSON → DuckDB persistente; destino Postgres (`full`/`delta`)
  com swap atômico.
- CLI: `check`, `discover`, `run`, `list`, `status`.
- Config centralizada em `clients.yml` (Pydantic Settings).
- Streams `clientes`, `contratos`, `titulos`.
