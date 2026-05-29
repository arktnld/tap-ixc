# Streams

Um **stream** mapeia um endpoint da API IXC para uma tabela de destino. Toda a
mecânica (paginação, retry, circuit breaker, staging, load, checkpoint) é cuidada
pela lib — o stream só declara metadados.

## Streams registrados

Três já vêm prontos. Todos suportam `strategy: full` e `strategy: delta`.

| Stream | Endpoint IXC | `replication_key` |
|---|---|---|
| `clientes` | `cliente` | `ultima_atualizacao` |
| `contratos` | `cliente_contrato` | `ultima_atualizacao` |
| `titulos` | `fn_areceber` | `ultima_atualizacao` |

Não é uma lista fechada — qualquer endpoint exposto pela API IXC pode virar um stream.

## A classe `Stream`

```python
class Stream:
    name: str                          # nome do stream e da tabela destino
    api_endpoint: str                  # endpoint na API IXC
    primary_keys: list[str] = ["id"]
    replication_key: str | None = None # campo para sync incremental
    schema: type[BaseModel] | None = None  # opcional: ativa VALIDATE
```

## Adicionar um stream

Dois passos.

### 1. Criar `tap_ixc/streams/<nome>.py`

```python
from tap_ixc.streams.base import Stream

class ChamadoStream(Stream):
    name = "chamados"                       # tabela destino
    api_endpoint = "su_oss_chamado"         # endpoint IXC
    replication_key = "ultima_atualizacao"  # None se não tiver modo delta
```

### 2. Registrar em `tap_ixc/streams/__init__.py`

```python
from tap_ixc.streams.chamados import ChamadoStream

STREAM_REGISTRY = {
    # ...
    ChamadoStream.name: ChamadoStream,
}
```

Pronto. Depois é só referenciar `chamados` no `clients.yml`:

```yaml
endpoints:
  - name: chamados
    api_endpoint: su_oss_chamado
    strategy: delta
    pk_column: id
```

## Validação com schema (dead letter)

Defina `schema` (um modelo pydantic) para ativar o stage `VALIDATE`. Linhas que não
batem com o schema vão para `etl.dead_letters` — o batch não falha.

```python
from pydantic import BaseModel
from tap_ixc.streams.base import Stream

class ClienteSchema(BaseModel):
    id: int
    nome: str
    email: str | None = None

class ClienteStream(Stream):
    name = "clientes"
    api_endpoint = "cliente"
    replication_key = "ultima_atualizacao"
    schema = ClienteSchema          # ← ativa VALIDATE
```

Sem `schema`, o `VALIDATE` é pulado e só roda a sanitização básica
(`0000-00-00` → `null`, string vazia → `null`). Veja
[Incremental e validação](incremental-and-validation.md).
