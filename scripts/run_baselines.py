"""Run paper baseline experiments for EpiSOA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from episoa.baselines import direct_llm, episoa_full, graph_retrieval, vanilla_rag
from episoa.config import ExperimentConfig, load_experiment_config
from episoa.evaluation.metrics import compute_metrics
from episoa.experiment import RunContext, configure_logging, save_config_snapshot
from episoa.llm.client import build_llm_client
from episoa.main import run_pipeline as run_runtime_pipeline
from episoa.main import write_jsonl
from episoa.pipeline import load_events, load_evidence
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


BaselineRunner = Callable[[str | dict[str, Any], list[EvidenceRecord], dict[str, Any]], list[AttributionTuple]]

BASELINE_RUNNERS: dict[str, BaselineRunner] = {
    "direct_llm": direct_llm.run,
    "few_shot_llm": direct_llm.run,
    "vanilla_rag": vanilla_rag.run,
    "graph_rag_style": graph_retrieval.run,
    "event_only_retrieval": direct_llm.run,
}


def run_baselines(config: ExperimentConfig) -> dict[str, dict[str, str]]:
    """Run configured baselines and write per-method predictions and metrics."""
    config.validate_mode_requirements()
    run_dir = Path(config.output.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(run_dir / "run.log")
    save_config_snapshot(json.loads(config.model_dump_json()), run_dir / "config.yaml")

    events = load_events(config.data.event_query_path)
    if not events:
        raise ValueError(f"No events found in {config.data.event_query_path}")
    event = events[0]
    evidence_pool = load_evidence(config.data.evidence_path)
    runtime_config = config.to_runtime_dict()
    llm_client = build_llm_client(runtime_config)
    outputs: dict[str, dict[str, str]] = {}

    method_configs = config.methods or {name: {} for name in [*BASELINE_RUNNERS, "episoa_full"]}
    for method_name in method_configs:
        method_dir = run_dir / "baselines" / method_name
        method_dir.mkdir(parents=True, exist_ok=True)
        predictions_path = method_dir / "predictions.jsonl"
        metrics_path = method_dir / "metrics.json"
        method_config = {
            **dict(method_configs.get(method_name, {})),
            "llm_client": llm_client,
            "verifier_threshold": config.verifier.threshold,
        }

        if method_name == "episoa_full":
            rows = _run_episoa_full_baseline(config, runtime_config, event, evidence_pool, method_dir)
        else:
            runner = BASELINE_RUNNERS.get(method_name)
            if runner is None:
                raise ValueError(f"Unknown baseline '{method_name}'")
            rows = runner(event, evidence_pool, method_config)
            write_jsonl(rows, predictions_path)

        metrics = compute_metrics(
            predictions_path,
            config.data.gold_path,
            config.data.gold_event_chains_path,
            metrics_path=metrics_path,
            k=config.retrieval.top_k,
        )
        outputs[method_name] = {
            "predictions_path": str(predictions_path),
            "metrics_path": str(metrics_path),
        }
        print(f"[baseline:{method_name}] predictions={predictions_path} metrics={metrics_path}")

    _write_summary(run_dir / "baseline_summary.json", outputs)
    return outputs


def _run_episoa_full_baseline(
    config: ExperimentConfig,
    runtime_config: dict[str, Any],
    event: dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    method_dir: Path,
) -> list[AttributionTuple]:
    run_context = RunContext(
        run_id=f"{config.run_id}-baseline-episoa_full",
        run_dir=method_dir,
        config_path=method_dir / "config.yaml",
        predictions_path=method_dir / "predictions.jsonl",
        metrics_path=method_dir / "metrics.json",
        log_path=method_dir / "run.log",
        prompts_dir=method_dir / "prompts_used",
    )
    return run_runtime_pipeline(
        str(event.get("target_event") or event.get("event_description") or event.get("event") or ""),
        dict(event.get("time_window", {})),
        config=runtime_config,
        evidence_pool=evidence_pool,
        output_path=run_context.predictions_path,
        run_context=run_context,
    )


def _write_summary(path: Path, outputs: dict[str, dict[str, str]]) -> None:
    path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA paper baselines.")
    parser.add_argument("--config", default="configs/baselines.yaml", help="Baseline YAML config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_baselines(load_experiment_config(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
