"""Circuit breaker por endpoint + retry via stamina."""
from __future__ import annotations

import pybreaker
import structlog

log = structlog.get_logger()


class _BreakerListener(pybreaker.CircuitBreakerListener):
    """Loga transições de estado do circuit breaker via structlog."""

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState | None,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        log.warning(
            "circuit_breaker.state_change",
            breaker=cb.name,
            old=old_state.name if old_state else None,
            new=new_state.name,
        )


_LISTENER = _BreakerListener()

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
            listeners=[_LISTENER],
        )
    return _breakers[endpoint]


def reset_all() -> None:
    """Reseta todos os circuit breakers (útil em testes)."""
    _breakers.clear()
