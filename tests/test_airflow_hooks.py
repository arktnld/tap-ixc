"""Testes do callback de deadline (Airflow)."""
from unittest.mock import patch
from tap_ixc.airflow_hooks import deadline_missed


def test_logs_and_posts_webhook():
    with patch("httpx.post") as mock_post:
        deadline_missed(text="estourou", webhook_url="https://hook")
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["json"] == {"text": "estourou"}


def test_no_webhook_no_post():
    with patch("httpx.post") as mock_post:
        deadline_missed(text="estourou")
    mock_post.assert_not_called()


def test_webhook_error_non_fatal():
    with patch("httpx.post", side_effect=RuntimeError("down")):
        deadline_missed(text="x", webhook_url="https://hook")   # não levanta
