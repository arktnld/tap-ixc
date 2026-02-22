"""Catalog — quais streams sincronizar e como.

Inspirado no Singer SDK (sdk.meltano.com):
- Catalog: conjunto de streams selecionados
- CatalogEntry: um stream + seu modo de sync + configuração de destino
- SyncMode: FULL (substitui tudo) | INCREMENTAL (só novos/alterados)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from tap_ixc.streams.base import Stream


class SyncMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass
class CatalogEntry:
    """Configura como um stream é sincronizado para o destino."""
    stream: type["Stream"]
    destination_table: str
    sync_mode: SyncMode = SyncMode.FULL
    selected_fields: list[str] | None = None  # None = todos
    pk_column: str = "id"
    transform_sql: str | None = None           # sobrescreve selected_fields
    page_size: int | None = None               # None = usa default do IXCClient (5000)


@dataclass
class Catalog:
    """Conjunto de streams a sincronizar."""
    entries: list[CatalogEntry] = field(default_factory=list)

    def select(self, *names: str) -> "Catalog":
        """Retorna novo Catalog apenas com os streams indicados."""
        name_set = set(names)
        selected = [e for e in self.entries if e.stream.name in name_set]
        missing = name_set - {e.stream.name for e in selected}
        if missing:
            available = [e.stream.name for e in self.entries]
            raise ValueError(
                f"Streams não encontrados: {sorted(missing)}. "
                f"Disponíveis: {available}"
            )
        return Catalog(selected)

    def __iter__(self) -> Iterator[CatalogEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        names = [e.stream.name for e in self.entries]
        return f"Catalog(streams={names})"
