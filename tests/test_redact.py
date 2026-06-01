"""Testes para redação de secrets."""
from tap_ixc.core.redact import redact


def test_redacts_dsn_password():
    assert redact("postgresql://etl:senha@host/db") == "postgresql://etl:***@host/db"
    assert "senha" not in redact("erro: postgres://u:p4ss@h:5432/db caiu")


def test_passthrough_plain_text():
    assert redact("role x does not exist") == "role x does not exist"


def test_handles_none_and_empty():
    assert redact(None) is None
    assert redact("") == ""
