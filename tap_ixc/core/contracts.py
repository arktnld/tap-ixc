"""Validação de batch com dead letter por row (nunca falha o batch inteiro)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Type

import structlog
from pydantic import BaseModel, ValidationError

log = structlog.get_logger()

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def sanitize(record: dict[str, Any]) -> dict[str, Any]:
    """
    Substitui strings vazias e datas inválidas (0000-00-00, 2024-03-00, etc.) por None.
    Migrado do sistema legado.
    """
    out: dict[str, Any] = {}
    for k, v in record.items():
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                out[k] = None
                continue
            if _DATE_PREFIX.match(stripped):
                parts = stripped[:10].split("-")
                if len(parts) == 3:
                    y, m, d = parts
                    if y == "0000" or m == "00" or d == "00":
                        out[k] = None
                        continue
                    try:
                        datetime.strptime(stripped[:10], "%Y-%m-%d")
                    except ValueError:
                        out[k] = None
                        continue
        out[k] = v
    return out


def validate_batch(
    records: list[dict[str, Any]],
    schema: Type[BaseModel] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Sanitiza e valida um batch.
    Retorna (válidos, dead_letter).
    Se schema=None, apenas sanitiza.
    """
    valid: list[dict[str, Any]] = []
    dead: list[dict[str, Any]] = []

    for raw in records:
        clean = sanitize(raw)
        if schema is None:
            valid.append(clean)
            continue
        try:
            obj = schema.model_validate(clean)
            valid.append(obj.model_dump())
        except ValidationError as exc:
            dead.append({"record": clean, "errors": exc.errors()})

    if dead:
        log.warning("contracts.dead_letter", count=len(dead), total=len(records))

    return valid, dead
