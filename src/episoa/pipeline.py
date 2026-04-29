"""Unified EpiSOA pipeline API for reproducible experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from episoa.config import ExperimentConfig
from episoa.evaluation.evaluator import evaluate
from episoa.evaluation.metrics import ensure_paper_metric_keys
from episoa.experiment import RunContext, configure_logging, get_logger, save_config_snapshot, set_random_seed
from episoa.main import run_pipeline as run_episoa_pipeline
from episoa.schemas.evidence import EvidenceRecord


@dataclass(frozen=True)
class PipelineResult:
    """Artifacts and aggregate counts produced by one pipeline run."""

    run_id: str
    run_dir: Path
    predictions_path: Path
    report_path: Path
    config_path: Path
    num_events: int
    num_predictions: int
    metrics: dict[str, Any]


logger = get_logger("pipeline")


def run_pipeline(config: ExperimentConfig) -> PipelineResult:
    """Run a single configured EpiSOA experiment and return output metadata."""
    config.validate_mode_requirements()
    set_random_seed(config.seed)

    run_dir = Path(config.output.run_dir)
    prompts_dir = run_dir / "prompts_used"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    run_context = RunContext(
        run_id=config.run_id,
        run_dir=run_dir,
        config_path=run_dir / "config.yaml",
        predictions_path=run_dir / "predictions.jsonl",
        metrics_path=run_dir / "metrics.json",
        log_path=run_dir / "run.log",
        prompts_dir=prompts_dir,
    )
    configure_logging(run_context.log_path)

    save_config_snapshot(_config_snapshot(config), run_context.config_path)
    _write_latest_run(run_dir)
    logger.info("Starting unified pipeline run_id=%s run_dir=%s", config.run_id, run_dir)

    events = load_events(config.data.event_query_path)
    if not events:
        raise ValueError(f"No events found in {config.data.event_query_path}")
    event = events[0]
    event_description = _event_description(event)
    time_window = dict(event.get("time_window", {}))
    evidence_pool = load_evidence(config.data.evidence_path)
    logger.info("Loaded %s event(s) and %s evidence records", len(events), len(evidence_pool))

    runtime_config = config.to_runtime_dict()
    runtime_config["evaluation"] = {
        **dict(runtime_config.get("evaluation", {})),
        "gold_path": config.data.gold_path,
        "gold_event_chains_path": config.data.gold_event_chains_path,
    }
    run_episoa_pipeline(
        event_description,
        time_window,
        config=runtime_config,
        evidence_pool=evidence_pool,
        output_path=run_context.predictions_path,
        run_context=run_context,
    )

    metrics = _evaluate_if_available(config, run_context)
    save_config_snapshot(_config_snapshot(config), run_context.config_path)
    report_path = write_summary_json(
        config,
        run_context,
        num_events=len(events),
        num_predictions=count_jsonl_rows(run_context.predictions_path),
        metrics=metrics,
    )
    _write_latest_run(run_dir)
    logger.info("Unified pipeline complete run_id=%s predictions=%s", config.run_id, run_context.predictions_path)

    return PipelineResult(
        run_id=config.run_id,
        run_dir=run_dir,
        predictions_path=run_context.predictions_path,
        report_path=report_path,
        config_path=run_context.config_path,
        num_events=len(events),
        num_predictions=count_jsonl_rows(run_context.predictions_path),
        metrics=metrics,
    )


def load_events(path: str | Path) -> list[dict[str, Any]]:
    """Load event query rows from JSON or JSONL."""
    event_path = Path(path)
    if event_path.suffix.lower() == ".json":
        payload = json.loads(event_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else [payload]
    return load_jsonl(event_path)


def load_evidence(path: str | Path) -> list[EvidenceRecord]:
    """Load EvidenceRecord objects from JSONL."""
    records: list[EvidenceRecord] = []
    for row in load_jsonl(path):
        evidence_row = dict(row)
        evidence_row.pop("event_id", None)
        records.append(EvidenceRecord.model_validate(evidence_row))
    if not records:
        raise ValueError(f"No evidence found in {path}")
    return records


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_summary_json(
    config: ExperimentConfig,
    run_context: RunContext,
    *,
    num_events: int,
    num_predictions: int,
    metrics: dict[str, Any],
) -> Path:
    """Write a compact machine-readable run summary."""
    report_path = run_context.run_dir / "summary.json"
    payload = {
        "mode": config.mode,
        "is_formal_paper_result": config.is_formal_paper_run(),
        "result_scope": "formal_paper_experiment" if config.is_formal_paper_run() else "mock_or_ablation_smoke_only",
        "run_id": run_context.run_id,
        "seed": config.seed,
        "dataset_name": config.data.dataset_name,
        "llm_model": config.model.llm_model,
        "embedding_model": config.model.embedding_model,
        "reranker_model": config.model.reranker_model,
        "disabled_modules": config.disabled_modules(),
        "run_dir": str(run_context.run_dir),
        "predictions_path": str(run_context.predictions_path),
        "metrics_path": str(run_context.metrics_path),
        "config_path": str(run_context.config_path),
        "num_events": num_events,
        "num_predictions": num_predictions,
        "metrics": metrics,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def count_jsonl_rows(path: str | Path) -> int:
    file_path = Path(path)
    if not file_path.exists():
        return 0
    return sum(1 for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip())


def _evaluate_if_available(config: ExperimentConfig, run_context: RunContext) -> dict[str, Any]:
    gold_path = Path(config.data.gold_path)
    gold_event_chains_path = Path(config.data.gold_event_chains_path) if config.data.gold_event_chains_path else None
    if gold_path.exists() and gold_event_chains_path is not None and gold_event_chains_path.exists():
        metrics = evaluate(
            run_context.predictions_path,
            gold_path,
            gold_event_chains_path,
            metrics_path=run_context.metrics_path,
        )
        metrics = ensure_paper_metric_keys(dict(metrics))
        run_context.metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return metrics
    if run_context.metrics_path.exists():
        try:
            return json.loads(run_context.metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    run_context.metrics_path.write_text("{}\n", encoding="utf-8")
    return {}


def _event_description(event: dict[str, Any]) -> str:
    value = event.get("target_event") or event.get("event_description") or event.get("event") or ""
    if not str(value).strip():
        raise ValueError("Event query must include target_event, event_description, or event")
    return str(value)


def _config_snapshot(config: ExperimentConfig) -> dict[str, Any]:
    return json.loads(config.model_dump_json())


def _write_latest_run(run_dir: Path) -> None:
    latest_path = Path("outputs/latest_run.txt")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(str(run_dir.resolve()), encoding="utf-8")
