"""Testes para o runner YAML — foco no disparo de webhook."""
from __future__ import annotations

from unittest.mock import patch

from tap_ixc.runner import _notify_webhook
from tap_ixc.tap import TapResult


def _results(ok=True):
    if ok:
        return [TapResult("clientes", 10, 10, "success")]
    return [
        TapResult("clientes", 10, 10, "success"),
        TapResult("titulos", 0, 0, "failed", error="API offline"),
    ]


class TestNotifyWebhook:
    def test_payload_success(self):
        with patch("tap_ixc.runner.httpx.post") as mock_post:
            _notify_webhook("https://hook", "gwg", _results(ok=True))
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert payload["client"] == "gwg"
        assert payload["status"] == "success"
        assert payload["streams"][0]["stream"] == "clientes"

    def test_payload_failed_when_any_stream_fails(self):
        with patch("tap_ixc.runner.httpx.post") as mock_post:
            _notify_webhook("https://hook", "gwg", _results(ok=False))
        payload = mock_post.call_args.kwargs["json"]
        assert payload["status"] == "failed"
        errs = [s["error"] for s in payload["streams"] if s["status"] == "failed"]
        assert errs == ["API offline"]

    def test_webhook_error_is_non_fatal(self):
        with patch("tap_ixc.runner.httpx.post", side_effect=RuntimeError("down")):
            # não deve levantar
            _notify_webhook("https://hook", "gwg", _results(ok=True))
