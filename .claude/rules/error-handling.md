---
paths: "**/*.py"
---
# Padrões de Erro

- Retry transiente: stamina com backoff exponencial (config por endpoint)
- Circuit breaker: pybreaker por endpoint, não por client. Abre após 5 falhas, reset 60s
- Falha permanente: captura, registra em `events.finish_run(status="FAILED")`, propaga
- Nunca silenciar exceções — sempre registrar no pipeline_events antes de re-raise
- Nunca usar bare `except:` — sempre especificar o tipo de exceção
- `TapResult.status = "failed"` com `error=str(exc)` — sync nunca levanta para o caller
- Dead letter por row na validação (`contracts.py`) — nunca falhar o batch inteiro
