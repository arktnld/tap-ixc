"""Stream — base class para todos os streams IXC.

Subclasses definem apenas metadados (name, api_endpoint, keys).
A lógica de paginação, retry e circuit breaker fica no IXCClient.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from tap_ixc.catalog import SyncMode
    from tap_ixc.extractors.api import IXCClient


class Stream:
    """
    Representa um stream de dados da API IXC.

    Para criar um novo stream, basta herdar e definir os atributos:

        class MeuStream(Stream):
            name = "meu_stream"
            api_endpoint = "meu_endpoint"
            replication_key = "ultima_atualizacao"  # para modo incremental
    """

    name: str
    api_endpoint: str
    primary_keys: list[str] = ["id"]
    replication_key: str | None = None  # campo para sync incremental

    def get_records(
        self,
        client: "IXCClient",
        sync_mode: "SyncMode",
        since: str | None = None,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Retorna registros da API. Delega paginação ao IXCClient."""
        from tap_ixc.catalog import SyncMode as SM

        strategy = (
            "delta"
            if sync_mode == SM.INCREMENTAL and self.replication_key
            else "full"
        )
        yield from client.paginate(
            endpoint=self.api_endpoint,
            strategy=strategy,
            incremental_since=since,
            page_size=page_size,
        )
