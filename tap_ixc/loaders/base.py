"""Protocols base para loaders."""
from __future__ import annotations

from typing import Any, Iterator, Protocol


class StagingProtocol(Protocol):
    def load(self, records: Iterator[dict[str, Any]]) -> tuple[str, int]:
        """Retorna (data_path, total_records)."""
        ...


class DestinationProtocol(Protocol):
    def load(self) -> int:
        """Carrega staging para destino. Retorna count de registros."""
        ...
