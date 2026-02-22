# tap-ixc

Lib Python para sincronizar dados da API  do **IXC** para PostgreSQL.

## Instalação

```bash
pip install tap-ixc
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

# Verifica conexão
ok, err = tap.check_connection()

# Descobre streams disponíveis
catalog = tap.discover()
# → clientes, contratos, titulos

# Sincroniza
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
# Configura variáveis de ambiente
export ETL_MONITOR_DSN="postgresql://user:pass@host/etl_monitor"
export MINHA_API_BASE_URL="https://..."
export MINHA_API_TOKEN="user:token"

# Executa
tap-ixc run minha-empresa --stream clientes
tap-ixc run minha-empresa                    # todos os streams
tap-ixc run minha-empresa --from-checkpoint  # retoma do último checkpoint

# Utilitários
tap-ixc check minha-empresa     # verifica credenciais
tap-ixc discover minha-empresa  # lista streams e modos de sync
tap-ixc list                    # lista clientes configurados
tap-ixc status                  # últimos 20 runs
```

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
      strategy: delta
      pk_column: id
```

## Streams disponíveis

Todos os streams suportam `strategy: full` e `strategy: delta` — você configura por endpoint no `clients.yml`.

| Stream | Endpoint IXC |
|---|---|
| `clientes` | `cliente` |
| `contratos` | `cliente_contrato` |
| `titulos` | `fn_areceber` |


## Monitoramento

A lib grava automaticamente em um schema PostgreSQL dedicado:

```bash
export ETL_MONITOR_DSN="postgresql://user:pass@host/db"
export ETL_MONITOR_SCHEMA="etl"  # opcional, padrão: etl

# Inicializa as tabelas
psql $ETL_MONITOR_DSN -f docs/schema.sql
```

Tabelas criadas: `pipeline_runs`, `checkpoints`, `pipeline_events`.

## Desenvolvimento

```bash
git clone https://github.com/arktnld/tap-ixc
cd tap-ixc
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

## Licença

MIT — veja [LICENSE](LICENSE).
