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
from typing import Any

import structlog

from tap_ixc.catalog import Catalog, CatalogEntry, SyncMode
from tap_ixc.config.settings import ApiConfig, Settings
from tap_ixc.core.checkpoint import Checkpoint
from tap_ixc.core.contracts import validate_batch
from tap_ixc.core.events import EventStore
from tap_ixc.core.pipeline import PipelineContext, PipelineRun, Stage
from tap_ixc.extractors.api import IXCClient
from tap_ixc.loaders.postgres import PostgresLoader
from tap_ixc.loaders.staging import StagingLoader
from tap_ixc.streams import STREAM_REGISTRY
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


def _advance_cursor(current: str | None, candidate: Any) -> str | None:
    """Retorna o maior cursor entre o atual e o candidato.

    Timestamps IXC ("YYYY-MM-DD HH:MM:SS") são lexicograficamente ordenáveis.
    Ignora candidatos None/vazios.
    """
    if candidate is None or candidate == "":
        return current
    cand = str(candidate)
    if current is None:
        return cand
    return max(current, cand)


class IXCTap:
    """
    Tap IXC — sincroniza streams de uma API IXC para Postgres.

    Streams disponíveis por padrão: clientes, contratos, titulos.
    """

    # Fonte única: o registry. Adicionar stream lá reflete aqui automaticamente.
    STREAMS: list[type[Stream]] = list(STREAM_REGISTRY.values())

    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._client = IXCClient(
            base_url=config.base_url,
            token=config.token,
            max_retries=config.max_retries,
            timeout_s=config.timeout_s,
            backoff_factor=config.backoff_factor,
            wait_jitter=config.wait_jitter,
            session_renewal_every=config.session_renewal_every,
            rate_limit_sleep=config.rate_limit_sleep,
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
        checkpoint = Checkpoint(settings.monitor_dsn, schema=settings.monitor_schema)
        events = EventStore(settings.monitor_dsn, schema=settings.monitor_schema)

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
        rep_key = stream.replication_key

        # Incremental: retoma do último cursor salvo no checkpoint, não de
        # "ontem meia-noite" hardcoded — assim pular um run não perde dados.
        since: str | None = None
        if entry.sync_mode == SyncMode.INCREMENTAL and rep_key:
            last_cp = checkpoint.get_last(client_id, entry.destination_table)
            if last_cp and last_cp.get("metadata"):
                since = last_cp["metadata"].get("replication_key_value")

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
            cursor: dict[str, str | None] = {"v": since}

            def tracked(it):
                for rec in it:
                    if rep_key:
                        cursor["v"] = _advance_cursor(cursor["v"], rec.get(rep_key))
                    yield rec

            records = stream.get_records(
                self._client, entry.sync_mode, since=since, page_size=entry.page_size
            )
            ndjson_path, total = staging.load(tracked(records))
            ctx.set("data_path", ndjson_path)
            ctx.set("records_extracted", total)
            if rep_key and cursor["v"] is not None:
                ctx.set("new_cursor", cursor["v"])

        def validate_stage(ctx: PipelineContext) -> None:
            # Só roda quando o stream define schema (senão nem é registrado abaixo).
            # Extração vazia: nem tabela de staging existe — nada a validar.
            if ctx.get("records_extracted") == 0:
                ctx.set("records_valid", 0)
                return
            rows = staging.read_all()
            valid, dead = validate_batch(rows, schema=stream.schema)
            if dead:
                events.write_dead_letters(ctx.get("run_id"), stream.name, dead)
                ctx.set("records_dead", len(dead))
            staging.replace(valid)
            ctx.set("records_valid", len(valid))

        def load_stage(ctx: PipelineContext) -> None:
            # Extração vazia (ex: incremental sem mudanças): nada a carregar.
            # Não dropa/recria a tabela à toa — vira no-op de sucesso.
            if ctx.get("records_extracted") == 0:
                ctx.set("records_loaded", 0)
                return
            ctx.set("records_loaded", pg_loader.load())

        def verify_stage(ctx: PipelineContext) -> None:
            loaded = ctx.get("records_loaded", 0)
            extracted = ctx.get("records_extracted")
            # EXTRACT pulado (resume via --from-checkpoint): não há contagem
            # desta sessão para comparar — confia no checkpoint anterior.
            if extracted is None:
                return
            if extracted > 0 and loaded == 0:
                raise RuntimeError(
                    f"Verificação falhou: {extracted} extraídos, 0 carregados"
                )
            # Se VALIDATE rodou, o esperado é o nº de válidas (dead letters saíram).
            expected = ctx.get("records_valid", extracted)
            if loaded != expected:
                raise RuntimeError(
                    f"Contagem divergente: {expected} esperados, {loaded} carregados"
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
            stages = {
                Stage.EXTRACT: extract_stage,
                Stage.LOAD: load_stage,
                Stage.VERIFY: verify_stage,
            }
            if stream.schema is not None:
                stages[Stage.VALIDATE] = validate_stage

            ctx = pipeline.execute(stages)
            # Avança o cursor SÓ após EXTRACT+LOAD+VERIFY ok. Se LOAD falhar,
            # o cursor não anda e o próximo run rebusca a mesma janela.
            new_cursor = ctx.get("new_cursor")
            if new_cursor is not None:
                checkpoint.mark_done(
                    client_id,
                    entry.destination_table,
                    Stage.VERIFY.value,
                    data_path=ctx.get("data_path"),
                    metadata={"replication_key_value": new_cursor},
                )
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
