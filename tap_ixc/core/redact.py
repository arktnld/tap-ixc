"""Redação de secrets em mensagens (erros, logs, webhooks)."""
from __future__ import annotations

import re

# Senha em DSN: scheme://user:senha@host  →  scheme://user:***@host
_DSN_PWD = re.compile(r"(://[^:/@\s]+:)[^@/\s]+(@)")


def redact(text: str | None) -> str | None:
    """Remove senhas de DSNs em `text`. Idempotente; passa None/'' adiante."""
    if not text:
        return text
    return _DSN_PWD.sub(r"\1***\2", text)
