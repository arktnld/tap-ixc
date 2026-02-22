"""Protocol base para extractors."""
from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class Extractor(Protocol):
    def extract(
        self,
        endpoint: str,
        strategy: str,
        incremental_since: str | None,
    ) -> Iterator[dict[str, Any]]:
        ...
