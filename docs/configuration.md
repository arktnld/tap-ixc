# Configuração

Toda a configuração de clientes vive em **`config/clients.yml`** — *single source of
truth*. Cada chave de topo é um cliente.

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
    backoff_factor: 0.5
  endpoints:
    - name: clientes
      api_endpoint: cliente
      strategy: full
      page_size: 5000
    - name: titulos
      api_endpoint: fn_areceber
      strategy: delta
      pk_column: id
  webhook_url: "${EMPRESA_WEBHOOK_URL}"
```

## Literal ou variável de ambiente

`token`, `postgres_dsn`, `base_url` e `webhook_url` aceitam **valor literal** ou
**`${VAR}`** (expandido de variáveis de ambiente). Pode misturar.

- **literal** — prático para dev local
- **`${VAR}`** — preferível para secrets de produção (não vai pro disco em texto puro)

!!! tip "Aviso de variável faltando"
    Se você usa `${MINHA_VAR}` e esquece de exportá-la, ao rodar aquele cliente a
    CLI avisa: *"variável de ambiente 'MINHA_VAR' não definida (campo 'api.token')"*
    — em vez de falhar com um 401 confuso mais adiante.

## Campos do cliente

| Campo | Obrigatório | Padrão | Descrição |
|---|---|---|---|
| `system` | sim | — | Sempre `ixc` nesta lib |
| `schema_name` | sim | — | Schema Postgres de **destino** dos dados |
| `postgres_dsn` | sim | — | DSN do Postgres de destino |
| `duckdb_path` | não | `/tmp/etl-staging/{client}.duckdb` | Arquivo DuckDB de staging (`{client}` é substituído) |
| `api` | sim | — | Bloco de API (abaixo) |
| `endpoints` | sim | `[]` | Lista de endpoints a sincronizar (abaixo) |
| `webhook_url` | não | `null` | Recebe um POST com o resumo ao fim de cada `run` |

## Bloco `api`

| Campo | Padrão | Descrição |
|---|---|---|
| `base_url` | — | URL do webservice IXC (ex: `https://.../webservice/v1`) |
| `token` | — | Credencial no formato `usuario:token` |
| `max_retries` | `3` | Tentativas em erro transiente (stamina) |
| `backoff_factor` | `0.5` | Base do backoff exponencial (segundos) |
| `timeout_s` | `60` | Timeout por requisição HTTP |
| `wait_jitter` | `1.0` | Jitter no backoff (anti-thundering-herd) |
| `session_renewal_every` | `0` | Recria a sessão HTTP a cada N páginas (`0` = desligado) |
| `rate_limit_sleep` | `0.0` | Pausa entre páginas, em segundos (`0` = desligado) |

## Bloco `endpoints`

Cada item vira um stream sincronizado.

| Campo | Padrão | Descrição |
|---|---|---|
| `name` | — | Nome do stream **e** da tabela de destino |
| `api_endpoint` | — | Endpoint na API IXC (ex: `cliente`, `fn_areceber`) |
| `strategy` | `full` | `full` (DROP+CREATE) ou `delta` (incremental por `ultima_atualizacao`) |
| `pk_column` | `id` | Chave usada no `delta` (DELETE+INSERT) |
| `page_size` | `5000` | Registros por página |
| `fields` | `null` | Lista de colunas a manter (`null` = todas). Útil para **excluir dados sensíveis** |
| `transform_sql` | `null` | SQL custom com `{raw}` no lugar da origem — sobrescreve `fields` |

### `fields` — projetar/excluir colunas

```yaml
- name: clientes
  api_endpoint: cliente
  strategy: full
  fields: [id, nome, cpf_cnpj, email, status, data_cadastro]   # exclui senha etc.
```

!!! warning "Dados sensíveis"
    O endpoint `cliente` do IXC retorna campos sensíveis como `senha` e
    `senha_hotsite_md5`. Sem `fields`, **todas** as colunas (incluindo hashes de
    senha) vão para o destino. Liste explicitamente os campos que você precisa
    para não levar credenciais ao warehouse.

### `transform_sql` — transformação custom

`{raw}` é substituído pela origem (NDJSON da extração). Sobrescreve `fields`.

```yaml
- name: titulos
  api_endpoint: fn_areceber
  strategy: delta
  pk_column: id
  transform_sql: "SELECT id, id_cliente, valor, vencimento FROM {raw} WHERE status = 'A'"
```

!!! note "Identificadores são validados"
    `name`/`schema_name`/`pk_column` são interpolados em SQL — a lib valida que são
    identificadores seguros (`^[A-Za-z_][A-Za-z0-9_]*$`) e rejeita injeção via YAML.

## Banco de monitoramento

Separado do destino, configurado por variáveis de ambiente (prefixo `ETL_`):

| Variável | Padrão | Descrição |
|---|---|---|
| `ETL_MONITOR_DSN` | `postgresql://etl:etl@localhost:5432/etl_monitor` | DSN do Postgres de monitoramento |
| `ETL_MONITOR_SCHEMA` | `etl` | Schema das tabelas de monitoramento |

Crie as tabelas uma vez:

```bash
psql "$ETL_MONITOR_DSN" -f docs/schema.sql
```

Veja [Monitoramento](monitoring.md) para o conteúdo das tabelas.
