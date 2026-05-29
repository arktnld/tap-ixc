# API Python

Para uso programático (ex: plataforma low-code), use `IXCTap` diretamente — sem
`clients.yml`. A referência completa, gerada do código, está em
[Referência da API](api-reference.md).

## Fluxo básico

```python
from tap_ixc.tap import IXCTap, Destination
from tap_ixc.config.settings import ApiConfig

# 1. cria o tap com as credenciais da API
tap = IXCTap(ApiConfig(
    base_url="https://minha-empresa.ixcsoft.com.br/webservice/v1",
    token="usuario:token",
))

# 2. valida credenciais (não levanta — retorna tupla)
ok, err = tap.check_connection()
if not ok:
    raise RuntimeError(err)

# 3. descobre os streams disponíveis
catalog = tap.discover()                 # Catalog com clientes, contratos, titulos

# 4. define o destino
destination = Destination(
    postgres_dsn="postgresql://user:pass@host/db",
    schema="public",
    duckdb_path="/tmp/etl-staging/minha-empresa.duckdb",
)

# 5. sincroniza (filtrando streams, se quiser)
results = tap.sync(destination, catalog.select("clientes", "titulos"))
for r in results:
    print(r.stream, r.status, r.records_loaded)
```

## `IXCTap`

| Método | Retorno | Descrição |
|---|---|---|
| `check_connection()` | `tuple[bool, str \| None]` | `(True, None)` se ok, `(False, msg)` se falhar |
| `discover()` | `Catalog` | Streams disponíveis; `INCREMENTAL` se tem `replication_key`, senão `FULL` |
| `sync(destination, catalog=None, from_checkpoint=False, client_id="default")` | `list[TapResult]` | Executa; `catalog=None` sincroniza tudo |

!!! note "Nunca levanta para o caller"
    `sync()` **nunca** propaga exceção — falhas viram `TapResult(status="failed",
    error=...)`. Você controla o fluxo inspecionando os resultados.

## `Destination`

```python
from tap_ixc.tap import Destination

Destination(
    postgres_dsn="postgresql://user:pass@host/db",  # destino dos dados
    schema="public",                                 # schema de destino
    duckdb_path="/tmp/staging.duckdb",               # arquivo de staging (persistente)
)
```

## `TapResult`

Retornado por stream:

```python
TapResult(
    stream="clientes",
    records_extracted=12435,
    records_loaded=12435,
    status="success",     # "success" | "failed"
    error=None,           # str em caso de falha
)
```

Padrão para detectar falha (ex: levantar no Airflow):

```python
results = tap.sync(destination)
falhas = [r for r in results if r.status == "failed"]
if falhas:
    raise RuntimeError(f"streams falharam: {[(r.stream, r.error) for r in falhas]}")
```

## `Catalog` e `CatalogEntry`

`Catalog` é o conjunto de streams; `CatalogEntry` configura **um** stream.

```python
from tap_ixc.catalog import Catalog, CatalogEntry, SyncMode
from tap_ixc.streams import ClienteStream

catalog = Catalog([
    CatalogEntry(
        stream=ClienteStream,
        destination_table="clientes",
        sync_mode=SyncMode.INCREMENTAL,   # ou SyncMode.FULL
        selected_fields=["id", "nome"],   # None = todas
        pk_column="id",
        transform_sql=None,               # SQL custom com {raw}
        page_size=5000,
    ),
])

# filtrar por nome
so_clientes = tap.discover().select("clientes")
```

`SyncMode`:

- `SyncMode.FULL` → `DROP + CREATE` (substitui tudo)
- `SyncMode.INCREMENTAL` → busca só o que mudou (`delta`), `DELETE + INSERT` por PK

## Configuração via YAML (runner)

Se preferir dirigir tudo pelo `clients.yml` (em vez de montar `ApiConfig`/`Destination`
na mão), use o `runner`:

```python
from tap_ixc.runner import run

results = run("minha-empresa")                       # todos os streams do YAML
results = run("minha-empresa", ["clientes"])         # só um
results = run("minha-empresa", from_checkpoint=True) # retoma
```

O `runner` também dispara o `webhook_url` do cliente ao fim, se configurado.
