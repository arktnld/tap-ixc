# tap-ixc

**Sincronize dados da API IXC Soft para PostgreSQL com uma chamada — e durma tranquilo.**

`tap-ixc` é uma biblioteca Python que extrai dados de provedores de internet que
rodam **IXC Soft** (clientes, contratos, títulos financeiros — ou qualquer endpoint
da API) e carrega no seu PostgreSQL. Diferente de um script `requests` + `INSERT`,
ela já vem com tudo que faz uma carga sobreviver ao mundo real: retoma de onde
parou, não derruba a tabela em produção se falhar no meio, e registra cada passo.

```python
from tap_ixc.tap import IXCTap, Destination
from tap_ixc.config.settings import ApiConfig

tap = IXCTap(ApiConfig(base_url="https://sua.ixcsoft.com.br/webservice/v1", token="user:token"))
results = tap.sync(Destination(
    postgres_dsn="postgresql://user:pass@host/db",
    schema="public",
    duckdb_path="/tmp/stg.duckdb",
))
# → [TapResult(stream="clientes", records_loaded=12435, status="success"), ...]
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

- 🔄 **Sync incremental por cursor** — baixa só o que mudou desde o último run
- ♻️ **Checkpoint por stage** (EXTRACT → VALIDATE → LOAD → VERIFY) — retoma sem refazer trabalho
- 🛡️ **Retry + circuit breaker por endpoint** — um endpoint instável não derruba os outros
- ⚛️ **Load atômico** — `full` (DROP+CREATE) ou `delta` (DELETE+INSERT por PK) via swap transacional
- 🧬 **Schema evolution** — coluna nova na origem é adicionada automaticamente no destino
- 🗑️ **Dead letter por linha** — registros inválidos vão para `etl.dead_letters`, o batch nunca falha inteiro
- 📊 **Observabilidade nativa** — `pipeline_runs`, `pipeline_events` e `checkpoints` no Postgres
- 🧩 **Qualquer endpoint IXC** vira um stream em [2 passos](streams.md#adicionar-um-stream)

## Por onde começar

<div class="grid cards" markdown>

- :material-rocket-launch: **[Primeiros passos](getting-started.md)** — do clone ao primeiro `run` em 6 passos
- :material-cog: **[Configuração](configuration.md)** — `clients.yml` campo a campo
- :material-console: **[CLI](cli.md)** — `check`, `run`, `status`...
- :material-language-python: **[API Python](python-api.md)** — uso programático
- :material-sitemap: **[Arquitetura](concepts.md)** — como funciona por dentro

</div>

## Inspiração

Arquitetura inspirada no [Singer SDK](https://sdk.meltano.com) (Meltano/Airbyte/Stitch).
Veja [Arquitetura](concepts.md#inspiracao-singer-sdk) para o que herdamos e onde divergimos.
