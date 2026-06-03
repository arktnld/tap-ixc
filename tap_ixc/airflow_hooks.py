"""Callbacks para Airflow — importáveis por dotted-path (lib instalada no worker).

Sem dependência de Airflow: as funções recebem strings (kwargs já renderizados
pelo template do Airflow) e fazem log + webhook opcional.
"""
from __future__ import annotations

import logging

log = logging.getLogger("airflow.task")


def deadline_missed(**kwargs: str) -> None:
    """Callback de `DeadlineAlert`: o sync passou do prazo configurado.

    Use com `SyncCallback("tap_ixc.airflow_hooks.deadline_missed", kwargs={...})`.
    kwargs esperados (templados no DAG): `text` (mensagem) e `webhook_url` (opcional).
    """
    msg = kwargs.get("text") or "tap-ixc: deadline do sync estourado"
    log.error(msg)
    url = kwargs.get("webhook_url")
    if url:
        try:
            import httpx
            httpx.post(url, json={"text": msg}, timeout=10)
        except Exception:
            log.warning("deadline webhook falhou")
