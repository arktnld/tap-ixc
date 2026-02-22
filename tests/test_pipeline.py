"""Testes para etl.core.pipeline — state machine."""
from unittest.mock import MagicMock

import pytest

from tap_ixc.core.pipeline import PipelineContext, PipelineRun, Stage


def _make_run(from_checkpoint: bool = False, last_stage: str | None = None) -> PipelineRun:
    checkpoint = MagicMock()
    checkpoint.get_last.return_value = (
        {"stage": last_stage, "data_path": None, "metadata": {}}
        if last_stage
        else None
    )

    events = MagicMock()
    events.start_run.return_value = 42

    return PipelineRun(
        client="gwg",
        system="ixc",
        pipeline="clientes",
        checkpoint=checkpoint,
        events=events,
        from_checkpoint=from_checkpoint,
    )


class TestPipelineRun:
    def test_all_stages_called(self):
        run = _make_run()
        called = []

        def extract(ctx: PipelineContext):
            called.append("EXTRACT")
            ctx.set("records_extracted", 10)

        def load(ctx: PipelineContext):
            called.append("LOAD")
            ctx.set("records_loaded", 10)

        def verify(ctx: PipelineContext):
            called.append("VERIFY")

        run.execute({
            Stage.EXTRACT: extract,
            Stage.LOAD: load,
            Stage.VERIFY: verify,
        })

        assert called == ["EXTRACT", "LOAD", "VERIFY"]

    def test_from_checkpoint_skips_done_stages(self):
        run = _make_run(from_checkpoint=True, last_stage="EXTRACT")
        called = []

        def extract(ctx: PipelineContext):
            called.append("EXTRACT")

        def load(ctx: PipelineContext):
            called.append("LOAD")
            ctx.set("records_loaded", 5)

        def verify(ctx: PipelineContext):
            called.append("VERIFY")

        run.execute({
            Stage.EXTRACT: extract,
            Stage.LOAD: load,
            Stage.VERIFY: verify,
        })

        assert "EXTRACT" not in called
        assert "LOAD" in called
        assert "VERIFY" in called

    def test_failed_stage_marks_run_as_failed(self):
        run = _make_run()

        def extract(ctx: PipelineContext):
            raise RuntimeError("API offline")

        with pytest.raises(RuntimeError, match="API offline"):
            run.execute({Stage.EXTRACT: extract})

        run._events.finish_run.assert_called_once()
        assert run._events.finish_run.call_args.kwargs["status"] == "FAILED"

    def test_context_passed_between_stages(self):
        run = _make_run()

        def extract(ctx: PipelineContext):
            ctx.set("records_extracted", 99)

        def load(ctx: PipelineContext):
            assert ctx.get("records_extracted") == 99
            ctx.set("records_loaded", 99)

        def verify(ctx: PipelineContext):
            assert ctx.get("records_loaded") == 99

        run.execute({
            Stage.EXTRACT: extract,
            Stage.LOAD: load,
            Stage.VERIFY: verify,
        })
