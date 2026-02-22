from tap_ixc.streams.base import Stream


class TituloStream(Stream):
    name = "titulos"
    api_endpoint = "fn_areceber"
    primary_keys = ["id"]
    replication_key = "ultima_atualizacao"
