---
paths: "**/*.py"
---
# Convenções Python

- Código síncrono — httpx.Client (não AsyncClient), sem asyncio
- `typing.Protocol` para interfaces — nunca ABC
- Pydantic v2 — nunca v1 compat
- structlog para logging — nunca print() ou logging stdlib direto
- Type hints obrigatórios em funções públicas
- Docstrings em módulos e classes, não em métodos óbvios

# Padrão Singer SDK (nossa inspiração)

Seguir a hierarquia: `IXCTap` → `Stream` → `IXCClient`

- Novos streams: herdar de `Stream`, definir `name`, `api_endpoint`, `replication_key`
- Nunca colocar lógica HTTP dentro de `Stream` — delegar ao `IXCClient`
- `IXCTap.sync()` é o único entry point de execução — nunca criar atalhos fora dele
- `CatalogEntry` é imutável após criação — não modificar campos em runtime
- `TapResult` é o retorno padrão — nunca levantar exceção de sync para o caller
