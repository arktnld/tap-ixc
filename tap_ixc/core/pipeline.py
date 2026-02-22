"""State machine: EXTRACT → VALIDATE → LOAD → VERIFY, cada stage checkpointado."""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable

import structlog

from tap_ixc.core.checkpoint import Checkpoint
from tap_ixc.core.events import EventStore

log = structlog.get_logger()


class Stage(str, Enum):
    EXTRACT = "EXTRACT"
    VALIDATE = "VALIDATE"
    LOAD = "LOAD"
    VERIFY = "VERIFY"


_STAGE_ORDER = [Stage.EXTRACT, Stage.VALIDATE, Stage.LOAD, Stage.VERIFY]

StageFn = Callable[["PipelineContext"], Any]


class PipelineContext:
    """Contexto compartilhado entre stages durante um run."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class PipelineRun:
    """
    Executa stages em ordem, respeitando checkpoints.
    """

    def __init__(
        self,
        client: str,
        system: str,
        pipeline: str,
        checkpoint: Checkpoint,
        events: EventStore,
        from_checkpoint: bool = False,
    ) -> None:
        self._client = client
        self._system = system
        self._pipeline = pipeline
        self._checkpoint = checkpoint
        self._events = events
        self._from_checkpoint = from_checkpoint

    def _last_done_stage(self) -> Stage | None:
        cp = self._checkpoint.get_last(self._client, self._pipeline)
        if not cp:
            return None
        try:
            return Stage(cp["stage"])
        except ValueError:
            return None

    def _should_skip(self, stage: Stage, last_done: Stage | None) -> bool:
        if not self._from_checkpoint or last_done is None:
            return False
        last_idx = _STAGE_ORDER.index(last_done)
        this_idx = _STAGE_ORDER.index(stage)
        return this_idx <= last_idx

    def execute(self, stages: dict[Stage, StageFn]) -> PipelineContext:
        ctx = PipelineContext()
        run_id = self._events.start_run(self._client, self._system, self._pipeline)
        last_done = self._last_done_stage() if self._from_checkpoint else None

        try:
            for stage in _STAGE_ORDER:
                if stage not in stages:
                    continue

                if self._should_skip(stage, last_done):
                    log.info("stage.skipped", stage=stage.value, pipeline=self._pipeline)
                    self._events.emit(run_id, "stage_skipped", stage=stage.value)
                    continue

                log.info("stage.start", stage=stage.value, pipeline=self._pipeline)
                self._events.emit(run_id, "stage_start", stage=stage.value)

                stages[stage](ctx)

                self._checkpoint.mark_done(
                    self._client,
                    self._pipeline,
                    stage.value,
                    data_path=ctx.get("data_path"),
                )
                self._events.emit(
                    run_id,
                    "stage_done",
                    stage=stage.value,
                    records=ctx.get("records_extracted"),
                )
                log.info("stage.done", stage=stage.value, pipeline=self._pipeline)

            self._events.finish_run(
                run_id,
                status="SUCCESS",
                records_in=ctx.get("records_extracted", 0),
                records_out=ctx.get("records_loaded", 0),
                stage=Stage.VERIFY.value,
            )
        except Exception as exc:
            log.error("pipeline.failed", pipeline=self._pipeline, error=str(exc))
            self._events.finish_run(
                run_id,
                status="FAILED",
                error=str(exc),
                records_in=ctx.get("records_extracted", 0),
            )
            raise

        return ctx
