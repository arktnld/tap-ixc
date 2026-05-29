# Contribuindo

Obrigado pelo interesse em contribuir com o tap-ixc.

## Ambiente

```bash
git clone https://github.com/arktnld/tap-ixc && cd tap-ixc
pip install -e ".[dev]"
pytest tests/ -v
```

## Antes de abrir um PR

- Mantenha o PR pequeno e focado (uma mudança lógica).
- `pytest tests/ -v` precisa passar.
- Siga as convenções de código (síncrono, structlog, pydantic v2, `Protocol`,
  type hints em funções públicas, sem `except` genérico).
- Atualize docs/README quando a mudança for user-facing.

O guia completo (convenções, como adicionar um stream, rodar a doc localmente)
está em **[arktnld.github.io/tap-ixc/contributing](https://arktnld.github.io/tap-ixc/contributing/)**.

Veja também o [guia de code review](https://arktnld.github.io/tap-ixc/code-review/).
