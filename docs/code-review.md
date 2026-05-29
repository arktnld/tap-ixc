# Guia de Code Review — tap-ixc

Técnicas destiladas das melhores discussões sobre code review (Google eng-practices,
Conventional Comments, estudos de PR size/latency). Adaptado para este projeto.
Fontes no fim.

## A pergunta única (north star)

Antes de aprovar, só um filtro:

> **Esta mudança deixa o código mais saudável?** (design mais claro, lógica mais limpa,
> testes melhores, menos risco) — **ou introduz algo que piora** (ilegibilidade,
> duplicação, fragilidade, regressão)?

Aprove quando a mudança melhora a saúde geral, **mesmo que não esteja perfeita**.
Review não é busca por perfeição — é evitar degradação. Um "melhor que antes" merge.

## O que o reviewer procura (checklist Google)

| Área | Ponto-chave |
|---|---|
| **Design** | A mudança faz sentido arquitetural e pertence a este lugar do código? |
| **Funcionalidade** | Faz o que diz — para o usuário final E para quem mantém depois? |
| **Complexidade** | Dá pra entender rápido? Rejeite over-engineering ("vamos precisar depois"). |
| **Testes** | Tem teste que de fato valida a mudança? Roda verde? |
| **Nomes** | Comunicam intenção sem virar parágrafo? |
| **Comentários** | Explicam o **porquê**, não repetem o **o quê**. |
| **Estilo** | Segue o style guide. Melhoria opcional → prefixo `Nit:`. |
| **Consistência** | Segue o padrão local quando o style guide é omisso. |
| **Docs** | Mudança user-facing atualizou README / docs / config exemplo? |

**Regra de ouro:** leia cada linha, entenda o contexto, e **elogie o que está bom**
junto com as correções.

## Checklist específico tap-ixc

Além do genérico, este projeto tem invariantes próprias (ver `.claude/rules/`):

- [ ] **`TapResult` nunca levanta** para o caller — falha vira `status="failed"`, `error=str(exc)`
- [ ] **CLI sai != 0** quando algum stream falha (Airflow/cron precisam detectar)
- [ ] **Load idempotente** — `full` (DROP+CREATE) ou `delta` (DELETE+INSERT por pk), sempre swap atômico
- [ ] **Dead letter por row** na validação — nunca falhar o batch inteiro
- [ ] **structlog**, nunca `print()` nem `logging` stdlib direto
- [ ] **httpx.Client síncrono** — sem `async`/asyncio
- [ ] **Pydantic v2**, **Protocol** para interfaces (nunca ABC, nunca v1 compat)
- [ ] **Type hints** em funções públicas; docstring em módulo/classe, não em método óbvio
- [ ] **Sem segredo em texto puro** — tokens/DSN via `${ENV_VAR}`, nunca literal commitado
- [ ] **Circuit breaker por endpoint**, retry transiente com stamina — não silenciar exceção
- [ ] **Cursor incremental só avança após sucesso total** (EXTRACT+LOAD+VERIFY)
- [ ] **Lógica HTTP fica no `IXCClient`**, nunca dentro de `Stream`
- [ ] **Novo stream** seguiu os 2 passos (classe + `STREAM_REGISTRY`)
- [ ] **Testes rodam verde** depois da mudança (`pytest tests/ -v`)

## PRs pequenas — o dado manda

Os números são consistentes em estudos de milhões de PRs:

- Eficácia **despenca acima de ~400 linhas**; sweet spot ~200 linhas (recomendação Google).
- PRs de 200–400 linhas têm **40% menos defeitos** que as maiores.
- PRs > 1000 linhas: **70% menos** detecção de defeito (o reviewer cansa e aprova no olho).
- PRs < 200 linhas são aprovadas **3x mais rápido**.

**Faça:** uma mudança lógica por PR. Refactor e feature em PRs separadas.
Se ficou grande, quebre — empilhe (stacked diffs) se precisar.

## Latência importa tanto quanto qualidade

- Review lento dreita até **40% da velocidade de entrega** do time.
- Benchmark de time elite: **primeiro comentário em < 7h** após abrir a PR.
- Cada round de review entre fusos pode somar 8–16h. Dois rounds = ~3 dias de calendário.

**Faça:** trate review como parte do trabalho, não tarefa "extra". Reserve uma fatia
do dia para PRs pendentes. Responda em rounds completos (não pingue 1 comentário por hora).

## Como comentar — Conventional Comments

Formato que torna a intenção explícita (e parseável por máquina):

```
<label> [decoração]: <assunto>

[discussão opcional — o porquê]
```

**Labels:**

| Label | Uso |
|---|---|
| `praise:` | Elogio. Deixe ao menos um por review. |
| `nitpick:` | Preferência trivial, **non-blocking**. |
| `suggestion:` | Propõe melhoria, com o motivo. |
| `issue:` | Problema concreto. Combina bem com uma `suggestion:`. |
| `question:` | Dúvida que precisa de resposta antes de decidir. |
| `thought:` | Ideia não-bloqueante, útil pra mentoria. |
| `todo:` | Mudança pequena mas necessária. |
| `chore:` | Tarefa de processo (link pra doc). |

**Decorações:** `(blocking)` resolve antes de aprovar · `(non-blocking)` não impede ·
`(if-minor)` autor pode pular se for trivial.

**Exemplos:**

```
nitpick (non-blocking): `cliente` poderia ser `client_cfg` pra bater com o resto.

issue (blocking): esse INSERT usa SELECT * — quebra se a origem ganhar coluna.
suggestion: inserir por nome de coluna explícito.

praise: bom isolar o cursor pra só avançar após VERIFY. Cobre o caso de LOAD falho.
```

## Tom

- Critique o **código**, não a pessoa. "Esse método faz X" > "Você fez X errado".
- Faça perguntas em vez de exigências quando há dúvida genuína.
- Dê o **porquê** — feedback sem motivo gera retrabalho cego.
- Marque o que é opinião (`nit`) vs o que bloqueia. O autor precisa saber o peso.
- Elogie de verdade. Custa uma linha, muda a cultura.

## Lado do autor — facilite o review

- **Descrição da PR:** o quê, **por quê**, e como testou. O reviewer não adivinha contexto.
- **Self-review primeiro:** leia seu próprio diff antes de pedir. Pega metade dos nits.
- **Responda tudo:** resolva ou explique cada comentário; não feche em silêncio.
- **Não misture:** rename + lógica na mesma PR esconde a mudança real no ruído do diff.

## Review assistido por IA — com ceticismo

Ferramentas de IA aceleram a primeira passada (lint, padrões, bugs óbvios), mas:

- **IA não entende intenção de negócio** nem o contexto do sistema. Não substitui o humano no design.
- Trate sugestão de IA como a de um júnior: **verifique antes de aplicar**. Pode "alucinar" problema que não existe ou perder o que importa.
- Use IA pra liberar o reviewer humano para o que ele faz melhor: **arquitetura e trade-offs**.

Neste repo: `/code-review` roda um review do diff atual; `/code-review ultra` faz review
multi-agente na nuvem. São apoio — a decisão de merge é humana.

---

## Fontes

- [How to do a code review — Google eng-practices](https://google.github.io/eng-practices/review/reviewer/) ([HN](https://news.ycombinator.com/item?id=20890682))
- [Conventional Comments](https://conventionalcomments.org/)
- [The Theatre of Pull Requests and Code Review (HN)](https://news.ycombinator.com/item?id=45371283)
- [Code review can be better (HN)](https://news.ycombinator.com/item?id=44967469)
- [What tone to use in code review suggestions (HN)](https://news.ycombinator.com/item?id=31858604)
- [A study of Google's Critique tooling (HN)](https://news.ycombinator.com/item?id=38518473)
- [There is an AI code review bubble (HN)](https://news.ycombinator.com/item?id=46766961)
- [The Hidden Cost of Slow Code Reviews: data from 8M PRs](https://dev.to/vitalii_petrenko_dev/the-hidden-cost-of-slow-code-reviews-data-from-8-million-prs-5fei)
- [PR Size Impact on Code Review Quality — Propel](https://www.propelcode.ai/blog/pr-size-impact-code-review-quality-data-study)
