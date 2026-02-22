"""Entry point: python -m etl <comando>"""
from __future__ import annotations

import sys
from typing import Any

import click
import structlog

log = structlog.get_logger()


def _configure_logging() -> None:
    import logging

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)


@click.group()
def cli() -> None:
    """ETL Framework IXC — cortex_ai2"""
    _configure_logging()


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@cli.command("run")
@click.argument("client")
@click.option("--stream", "streams", multiple=True, help="Stream(s) a sincronizar")
@click.option("--from-checkpoint", is_flag=True, default=False)
def run_cmd(client: str, streams: tuple[str, ...], from_checkpoint: bool) -> None:
    """Sincroniza streams de um cliente."""
    from tap_ixc.runner import run

    try:
        results = run(client, list(streams) or None, from_checkpoint)
        for r in results:
            icon = "✓" if r.status == "success" else "✗"
            click.echo(f"  {icon} {r.stream}: {r.records_loaded} registros")
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


@cli.command("discover")
@click.argument("client")
def discover_cmd(client: str) -> None:
    """Lista streams disponíveis e seus modos de sync padrão."""
    from tap_ixc.config.settings import get_client
    from tap_ixc.tap import IXCTap

    cfg = get_client(client)
    tap = IXCTap(cfg.api)
    catalog = tap.discover()

    click.echo(f"Streams disponíveis para '{client}':\n")
    for entry in catalog:
        fields = f" → {entry.selected_fields}" if entry.selected_fields else " → todos os campos"
        click.echo(f"  {entry.stream.name:<20} [{entry.sync_mode.value}]{fields}")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


@cli.command("check")
@click.argument("client")
def check_cmd(client: str) -> None:
    """Verifica se as credenciais do cliente são válidas."""
    from tap_ixc.config.settings import get_client
    from tap_ixc.tap import IXCTap

    cfg = get_client(client)
    tap = IXCTap(cfg.api)
    ok, err = tap.check_connection()

    if ok:
        click.echo(f"  ✓ Conexão com '{client}' ok.")
    else:
        click.echo(f"  ✗ Falha na conexão: {err}", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@cli.command("list")
def list_cmd() -> None:
    """Lista clientes configurados no clients.yml."""
    from tap_ixc.config.settings import load_clients

    clients = load_clients()
    for name, cfg in clients.items():
        streams = ", ".join(ep.name for ep in cfg.endpoints)
        click.echo(f"  {name:<20} [{cfg.system}] → {streams}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command("status")
@click.option("--client", default=None, help="Filtrar por cliente")
def status_cmd(client: str | None) -> None:
    """Status dos últimos 20 runs."""
    import psycopg

    from tap_ixc.config.settings import Settings

    settings = Settings()
    where = "WHERE client = %s" if client else ""
    params: tuple[Any, ...] = (client,) if client else ()

    with psycopg.connect(settings.monitor_dsn) as conn:
        rows = conn.execute(
            f"""
            SELECT client, pipeline, status, stage,
                   started_at, duration_s, records_out
            FROM etl.pipeline_runs
            {where}
            ORDER BY started_at DESC
            LIMIT 20
            """,
            params,
        ).fetchall()

    if not rows:
        click.echo("Nenhum run encontrado.")
        return

    header = (
        f"{'CLIENT':<15} {'STREAM':<20} {'STATUS':<10} "
        f"{'STAGE':<10} {'STARTED':<26} {'DUR':>7}  RECORDS"
    )
    click.echo(header)
    click.echo("-" * len(header))

    for r in rows:
        client_, pipeline, status, stage, started, dur, recs = r
        dur_str = f"{dur:.1f}s" if dur else "-"
        click.echo(
            f"{client_:<15} {pipeline:<20} {status:<10} "
            f"{(stage or '-'):<10} {str(started):<26} {dur_str:>7}  {recs or 0}"
        )
