<!-- Mantenha pequeno: eficácia de review cai acima de ~400 linhas. Uma mudança lógica por PR. -->

## O quê

<!-- Resumo da mudança em 1-2 linhas. -->

## Por quê

<!-- O problema/motivo. O reviewer não adivinha contexto. -->

## Como testei

<!-- pytest, run manual, etc. -->

---

### Checklist do autor

Geral:

- [ ] Uma mudança lógica (refactor e feature em PRs separadas)
- [ ] Fiz self-review do diff antes de pedir review
- [ ] `pytest tests/ -v` verde
- [ ] Docs/README/config exemplo atualizados se a mudança é user-facing

Invariantes tap-ixc (ver [`docs/code-review.md`](../docs/code-review.md)):

- [ ] `TapResult` nunca levanta para o caller; CLI sai `!= 0` se algum stream falha
- [ ] Load idempotente (`full` DROP+CREATE ou `delta` DELETE+INSERT por pk), swap atômico
- [ ] Dead letter por row na validação — batch nunca falha inteiro
- [ ] `structlog` (sem `print`/logging stdlib); httpx síncrono; pydantic v2; Protocol (não ABC)
- [ ] Type hints em funções públicas; sem segredo literal (`${ENV_VAR}`)
- [ ] Exceção específica (sem bare `except`); circuit breaker/retry preservados
- [ ] Cursor incremental só avança após EXTRACT+LOAD+VERIFY
- [ ] Lógica HTTP só no `IXCClient`; stream novo seguiu os 2 passos (classe + `STREAM_REGISTRY`)
- [ ] Sem config morta (campo definido e nunca lido)
