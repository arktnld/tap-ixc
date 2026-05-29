# Incremental e validação

## Sync incremental por cursor

Streams com `replication_key` e `strategy: delta` só baixam o que mudou desde o
último run bem-sucedido.

### Como funciona

1. Antes de extrair, a lib lê o último valor do cursor em `etl.checkpoints.metadata`.
2. Esse valor vira o filtro da API: `ultima_atualizacao >= cursor`.
3. Durante a extração, acompanha o maior `ultima_atualizacao` visto.
4. **Só depois** de `EXTRACT + LOAD + VERIFY` concluírem, grava o novo cursor.

```yaml
endpoints:
  - name: titulos
    api_endpoint: fn_areceber
    strategy: delta
    pk_column: id
```

### Garantias

- **Sem perda ao pular um run** — retoma do último ponto real (não de "ontem" fixo).
- **Seguro contra falha de LOAD** — se o load falha, o cursor não avança; a janela é
  rebuscada no próximo run.
- **Idempotente** — `delta` faz `DELETE + INSERT` por PK; re-buscar a linha de
  fronteira (boundary `>=`) não duplica.

!!! warning "Primeiro carregamento e deletes"
    - O backfill histórico inicial deve usar `strategy: full`.
    - O incremental **não** captura deletes na origem (só vê inserts/updates). Para
      reconciliar registros apagados, rode `strategy: full` periodicamente — o `full`
      recria a tabela e some com os órfãos.

### Run incremental vazio

Um dia sem mudanças → 0 registros extraídos → **no-op de sucesso** (não dropa nem
recria a tabela, não falha). Útil para crons diários.

## Sanitização (sempre)

Independente de schema, todo registro passa por `sanitize()`:

- string vazia (`""`) → `null`
- data inválida (`0000-00-00`, `2024-02-30`, mês/dia `00`) → `null`

> Em dados reais de IXC, datas-lixo são comuns (ex: `data_nascimento = "0000-00-00"`).
> A sanitização evita que quebrem o load.

## Validação com schema → dead letter

Quando o `Stream` define `schema` (pydantic), o stage `VALIDATE`:

1. Lê o staging,
2. valida cada linha com o schema,
3. manda as **reprovadas** para `etl.dead_letters` (com o erro),
4. mantém só as **válidas** para o `LOAD`.

O batch **nunca** falha por causa de uma linha ruim.

```python
from pydantic import BaseModel
from tap_ixc.streams.base import Stream

class ClienteSchema(BaseModel):
    id: int
    email: str          # registros sem email vão para dead letter

class ClienteStream(Stream):
    name = "clientes"
    api_endpoint = "cliente"
    schema = ClienteSchema
```

### Inspecionando dead letters

```sql
SELECT stream, record, errors, created_at
FROM etl.dead_letters
WHERE run_id = (SELECT max(id) FROM etl.pipeline_runs WHERE client = 'minha-empresa')
ORDER BY created_at DESC;
```

`record` (JSONB) tem a linha original; `errors` (JSONB) tem o detalhe pydantic do
que falhou.
