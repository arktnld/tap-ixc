"""Circuit breaker por endpoint + retry via stamina."""
from __future__ import annotations

import pybreaker
import structlog

log = structlog.get_logger()

# Registry global: um breaker por endpoint
_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def get_circuit_breaker(
    endpoint: str,
    fail_max: int = 5,
    reset_timeout: int = 60,
) -> pybreaker.CircuitBreaker:
    """Retorna (criando se necessário) o circuit breaker para o endpoint."""
    if endpoint not in _breakers:
        _breakers[endpoint] = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name=endpoint,
        )
    return _breakers[endpoint]


def reset_all() -> None:
    """Reseta todos os circuit breakers (útil em testes)."""
    _breakers.clear()
