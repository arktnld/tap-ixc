# Contribuindo

## Ambiente de desenvolvimento

```bash
git clone https://github.com/arktnld/tap-ixc && cd tap-ixc
pip install -e ".[dev]"
```

## Testes

```bash
pytest tests/ -v
```

A suíte cobre cada módulo com mocks (sem precisar de Postgres/API reais):

| Arquivo | Cobre |
|---|---|
| `test_tap.py` | `IXCTap` — discover, check, sync, cursor, VALIDATE, vazio, resume |
| `test_api_client.py` | `IXCClient` — paginação, params, check |
| `test_checkpoint.py` | CRUD de checkpoint |
| `test_pipeline.py` | state machine (stages, from_checkpoint, falhas) |
| `test_staging.py` | NDJSON → DuckDB, fields, transform_sql, read/replace |
| `test_postgres.py` | helpers de schema evolution, validação de identificador |
| `test_contracts.py` | sanitize, validate_batch, dead letter |
| `test_runner.py` | webhook |
| `test_settings.py` | carga de config, erros humanizados |

## Convenções

- Código **síncrono** — `httpx.Client` (não async).
- **structlog** para logging — nunca `print` ou logging stdlib direto.
- **Pydantic v2**, **`typing.Protocol`** para interfaces (não ABC).
- Type hints em funções públicas; docstrings em módulos e classes.
- Nunca `except` genérico sem tipo.
- `TapResult` é o retorno — `sync()` nunca levanta para o caller.

Veja também o [Guia de code review](code-review.md).

## Adicionar um stream

Dois passos — veja [Streams](streams.md#adicionar-um-stream).

## Documentação

A doc é MkDocs Material. Para rodar localmente:

```bash
pip install -e ".[docs]"
mkdocs serve          # http://127.0.0.1:8000
```

O deploy para GitHub Pages é automático (workflow `.github/workflows/docs.yml`) em
push na `master`.
