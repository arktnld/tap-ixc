"""IXCTap — entry point principal da lib.

Inspirado no Singer SDK (sdk.meltano.com).

Uso básico:
    tap = IXCTap(ApiConfig(base_url=..., token=...))

    # verifica credenciais
    ok, err = tap.check_connection()

    # descobre streams disponíveis
    catalog = tap.discover()

    # sincroniza streams escolhidos
    results = tap.sync(destination, catalog.select("clientes", "contratos"))
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

from tap_ixc.catalog import Catalog, CatalogEntry, SyncMode
from tap_ixc.config.settings import ApiConfig, Settings
from tap_ixc.core.checkpoint import Checkpoint
from tap_ixc.core.events import EventStore
from tap_ixc.core.pipeline import PipelineContext, PipelineRun, Stage
from tap_ixc.extractors.api import IXCClient
from tap_ixc.loaders.postgres import PostgresLoader
from tap_ixc.loaders.staging import StagingLoader
from tap_ixc.streams import ClienteStream, ContratoStream, TituloStream
from tap_ixc.streams.base import Stream

log = structlog.get_logger()


@dataclass
class Destination:
    """Configuração do destino Postgres."""
    postgres_dsn: str
    schema: str
    duckdb_path: str


@dataclass
class TapResult:
    """Resultado da sincronização de um stream."""
    stream: str
    records_extracted: int
    records_loaded: int
    status: str            # "success" | "failed"
    error: str | None = None


class IXCTap:
    """
    Tap IXC — sincroniza streams de uma API IXC para Postgres.

    Streams disponíveis por padrão: clientes, contratos, titulos.
    """

    STREAMS: list[type[Stream]] = [
        ClienteStream,
        ContratoStream,
        TituloStream,
    ]

    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._client = IXCClient(
            base_url=config.base_url,
            token=config.token,
            max_retries=config.max_retries,
            timeout_s=config.timeout_s,
            backoff_factor=config.backoff_factor,
        )

    def check_connection(self) -> tuple[bool, str | None]:
        """
        Verifica se as credenciais são válidas antes de rodar.
        Retorna (True, None) se ok, (False, mensagem) se falhar.
        """
        return self._client.check_connection()

    def discover(self) -> Catalog:
        """
        Retorna o Catalog com todos os streams disponíveis.
        sync_mode padrão: INCREMENTAL se o stream tem replication_key, FULL caso contrário.
        """
        entries = [
            CatalogEntry(
                stream=cls,
                destination_table=cls.name,
                sync_mode=SyncMode.INCREMENTAL if cls.replication_key else SyncMode.FULL,
                pk_column=cls.primary_keys[0],
            )
            for cls in self.STREAMS
        ]
        return Catalog(entries)

    def sync(
        self,
        destination: Destination,
        catalog: Catalog | None = None,
        from_checkpoint: bool = False,
        client_id: str = "default",
    ) -> list[TapResult]:
        """
        Sincroniza streams para o destino.

        catalog=None → sincroniza todos os streams disponíveis.
        client_id  → identificador gravado nos logs de observabilidade.
        """
        settings = Settings()
        checkpoint = Checkpoint(settings.monitor_dsn)
        events = EventStore(settings.monitor_dsn)

        active_catalog = catalog if catalog is not None else self.discover()
        results = []

        for entry in active_catalog:
            log.info("tap.stream_start", stream=entry.stream.name, mode=entry.sync_mode)
            result = self._sync_entry(
                entry, destination, checkpoint, events, from_checkpoint, client_id
            )
            results.append(result)
            log.info("tap.stream_done", stream=entry.stream.name, status=result.status)

        return results

    def _sync_entry(
        self,
        entry: CatalogEntry,
        destination: Destination,
        checkpoint: Checkpoint,
        events: EventStore,
        from_checkpoint: bool,
        client_id: str,
    ) -> TapResult:
        stream = entry.stream()

        staging = StagingLoader(
            duckdb_path=destination.duckdb_path,
            table=entry.destination_table,
            fields=entry.selected_fields,
            transform_sql=entry.transform_sql,
        )
        pg_loader = PostgresLoader(
            duckdb_path=destination.duckdb_path,
            pg_dsn=destination.postgres_dsn,
            schema=destination.schema,
            table=entry.destination_table,
            strategy=entry.sync_mode.value,
            pk_column=entry.pk_column,
        )

        def extract_stage(ctx: PipelineContext) -> None:
            records = stream.get_records(self._client, entry.sync_mode, page_size=entry.page_size)
            ndjson_path, total = staging.load(records)
            ctx.set("data_path", ndjson_path)
            ctx.set("records_extracted", total)

        def load_stage(ctx: PipelineContext) -> None:
            ctx.set("records_loaded", pg_loader.load())

        def verify_stage(ctx: PipelineContext) -> None:
            extracted = ctx.get("records_extracted", 0)
            loaded = ctx.get("records_loaded", 0)
            if extracted > 0 and loaded == 0:
                raise RuntimeError(
                    f"Verificação falhou: {extracted} extraídos, {loaded} carregados"
                )

        pipeline = PipelineRun(
            client=client_id,
            system="ixc",
            pipeline=entry.destination_table,
            checkpoint=checkpoint,
            events=events,
            from_checkpoint=from_checkpoint,
        )

        try:
            ctx = pipeline.execute({
                Stage.EXTRACT: extract_stage,
                Stage.LOAD: load_stage,
                Stage.VERIFY: verify_stage,
            })
            return TapResult(
                stream=stream.name,
                records_extracted=ctx.get("records_extracted", 0),
                records_loaded=ctx.get("records_loaded", 0),
                status="success",
            )
        except Exception as exc:
            return TapResult(
                stream=stream.name,
                records_extracted=0,
                records_loaded=0,
                status="failed",
                error=str(exc),
            )
