from tap_ixc.streams.base import Stream


class ContratoStream(Stream):
    name = "contratos"
    api_endpoint = "cliente_contrato"
    primary_keys = ["id"]
    replication_key = "ultima_atualizacao"
