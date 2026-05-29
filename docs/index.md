# tap-ixc

Biblioteca Python para sincronizar dados da **API IXC Soft** para **PostgreSQL** com
checkpointing por stage, retry, circuit breaker e observabilidade nativa.

```python
from tap_ixc.tap import IXCTap, Destination
from tap_ixc.config.settings import ApiConfig

tap = IXCTap(ApiConfig(base_url="https://sua.ixcsoft.com.br/webservice/v1", token="user:token"))
tap.sync(Destination(postgres_dsn="postgresql://user:pass@host/db", schema="public",
                     duckdb_path="/tmp/stg.duckdb"))
```

## Como esta documentação é organizada

Seguimos o [Diátaxis](https://diataxis.fr): quatro modos, cada um com um propósito.

<div class="grid cards" markdown>

-   :material-school: **Tutorial**

    Aprenda fazendo, do zero ao primeiro sync agendado.

    [:octicons-arrow-right-24: 10 minutos com tap-ixc](tutorial.md)

-   :material-wrench: **Guias (how-to)**

    Receitas para tarefas concretas: adicionar stream, excluir campos, agendar.

    [:octicons-arrow-right-24: Streams](streams.md) ·
    [Incremental](incremental-and-validation.md) ·
    [Deploy](deployment.md)

-   :material-book-open-variant: **Referência**

    Descrição precisa de cada campo, comando e classe.

    [:octicons-arrow-right-24: Configuração](configuration.md) ·
    [CLI](cli.md) ·
    [API](api-reference.md)

-   :material-lightbulb: **Explicação**

    Como funciona por dentro e por que as decisões foram tomadas.

    [:octicons-arrow-right-24: Arquitetura](concepts.md)

</div>

## Por que não um script `requests`?

| No mundo real | Script cru | tap-ixc |
|---|---|---|
| API caiu na página 800/1000 | recomeça do zero | retry + circuit breaker por endpoint |
| Run diário pulou um dia | perde dados | cursor incremental retoma do último ponto |
| Falha no meio do `INSERT` | tabela em prod vazia | swap atômico (staging → COMMIT) |
| 1 registro corrompido | derruba o batch | dead letter por linha |
| "Rodou? Quanto faltou?" | nenhuma pista | tabelas `etl.*` de observabilidade |

## Instalação rápida

```bash
pip install git+https://github.com/arktnld/tap-ixc.git
```

Setup completo do zero em [Primeiros passos](getting-started.md).

---

Inspirado no [Singer SDK](https://sdk.meltano.com) (Meltano/Airbyte/Stitch) —
veja [o que herdamos e onde divergimos](concepts.md#inspiracao-singer-sdk).
Código aberto sob [MIT](https://github.com/arktnld/tap-ixc/blob/master/LICENSE).
