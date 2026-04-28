"""Full EpiSOA baseline wrapper."""

from __future__ import annotations

from typing import Any

from episoa.baselines.direct_llm import event_description_from
from episoa.experiment import configure_logging, create_run_context
from episoa.main import run_pipeline
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


def run(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    """Run the complete EpiSOA pipeline and return AttributionTuple outputs."""
    config = config or {}
    event_description = event_description_from(event)
    time_window = dict(event.get("time_window", {})) if isinstance(event, dict) else {}
    run_context = config.get("run_context")
    if run_context is None:
        run_context = create_run_context(config.get("run_name", "episoa-full-baseline"))
        configure_logging(run_context.log_path)
    pipeline_config = {
        key: value
        for key, value in config.items()
        if key not in {"run_context", "output_path", "run_name"}
    }
    return run_pipeline(
        event_description,
        time_window,
        config=pipeline_config,
        evidence_pool=evidence_pool,
        output_path=config.get("output_path"),
        run_context=run_context,
    )


def run_baseline(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    return run(event, evidence_pool, config)
