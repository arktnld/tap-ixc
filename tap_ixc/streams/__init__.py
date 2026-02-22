"""Streams IXC disponíveis."""
from tap_ixc.streams.base import Stream
from tap_ixc.streams.clientes import ClienteStream
from tap_ixc.streams.contratos import ContratoStream
from tap_ixc.streams.titulos import TituloStream

# Registry: nome do stream → classe
# Usado pelo runner YAML para mapear endpoints configurados
STREAM_REGISTRY: dict[str, type[Stream]] = {
    ClienteStream.name: ClienteStream,
    ContratoStream.name: ContratoStream,
    TituloStream.name: TituloStream,
}

__all__ = [
    "Stream",
    "ClienteStream",
    "ContratoStream",
    "TituloStream",
    "STREAM_REGISTRY",
]
