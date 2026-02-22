from tap_ixc.streams.base import Stream


class ClienteStream(Stream):
    name = "clientes"
    api_endpoint = "cliente"
    primary_keys = ["id"]
    replication_key = "ultima_atualizacao"
