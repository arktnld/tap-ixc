"""Protocols base para loaders."""
from __future__ import annotations

import re
from typing import Any, Iterator, Protocol

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(name: str, what: str = "identificador") -> str:
    """Garante que um nome de tabela/schema/coluna vindo de config é seguro.

    Esses nomes são interpolados em SQL (DuckDB/Postgres) — validar contra um
    padrão estrito evita injeção via clients.yml. Retorna o nome se válido.
    """
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(
            f"{what} inválido: {name!r}. Use apenas letras, dígitos e '_' "
            f"(começando por letra ou '_')."
        )
    return name


class StagingProtocol(Protocol):
    def load(self, records: Iterator[dict[str, Any]]) -> tuple[str, int]:
        """Retorna (data_path, total_records)."""
        ...


class DestinationProtocol(Protocol):
    def load(self) -> int:
        """Carrega staging para destino. Retorna count de registros."""
        ...
