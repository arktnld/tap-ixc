"""Testes para circuit breaker — listeners e registro de estado."""
from __future__ import annotations

from unittest.mock import patch

import pybreaker
import pytest

from tap_ixc.core.retry import get_circuit_breaker, reset_all


class TestCircuitBreakerListener:
    def setup_method(self):
        reset_all()

    def test_state_change_is_logged(self):
        """Transição de estado deve emitir log estruturado."""
        breaker = get_circuit_breaker("test_endpoint", fail_max=1, reset_timeout=1)

        with patch("tap_ixc.core.retry.log") as mock_log:
            with pytest.raises(Exception):
                breaker.call(lambda: (_ for _ in ()).throw(Exception("falha")))

            mock_log.warning.assert_called_once()
            call_args = mock_log.warning.call_args
            assert "circuit_breaker.state_change" in call_args[0]

    def test_listener_logs_breaker_name(self):
        """Log deve incluir nome do endpoint."""
        breaker = get_circuit_breaker("meu_endpoint", fail_max=1, reset_timeout=1)

        with patch("tap_ixc.core.retry.log") as mock_log:
            with pytest.raises(Exception):
                breaker.call(lambda: (_ for _ in ()).throw(Exception("falha")))

            call_kwargs = mock_log.warning.call_args[1]
            assert call_kwargs.get("breaker") == "meu_endpoint"
