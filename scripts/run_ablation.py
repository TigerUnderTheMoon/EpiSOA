"""Run EpiSOA ablation settings and evaluate each prediction file."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from episoa.config import load_runtime_config
from episoa.evaluation.faithfulness_metrics import evaluate_jsonl
from episoa.experiment import RunContext, configure_logging, set_random_seed
from episoa.main import load_demo_inputs, run_pipeline
from episoa.schemas.evidence import EvidenceRecord


def load_config(path: str | Path) -> dict[str, Any]:
    return load_runtime_config(path)


def _pipeline_config_for_setting(config: dict[str, Any], setting_name: str) -> dict[str, Any]:
    base_ablation = dict(config.get("ablation", {}))
    setting_overrides = dict(config.get("settings", {}).get(setting_name, {}))
    ablation = {**base_ablation, **setting_overrides}
    return {
        "pipeline": dict(config.get("pipeline", {})),
        "collector": dict(config.get("collector", {})),
        "ablation": ablation,
    }


def safe_setting_name(setting_name: str) -> str:
    """Convert report-facing setting names into safe directory names."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", setting_name).strip("_")


def run_ablation_setting(
    config: dict[str, Any],
    setting_name: str,
    *,
    dataset_dir: str | Path | None = None,
    run_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    defaults = config.get("defaults", {})
    resolved_run_dir = resolve_run_dir(run_dir)
    safe_name = safe_setting_name(setting_name)
    prediction_path = resolved_run_dir / "predictions" / "ablations" / f"{safe_name}.jsonl"
    metrics_path = resolved_run_dir / "metrics" / "ablations" / f"{safe_name}.json"
    prompts_dir = resolved_run_dir / "prompts_used" / "ablations" / safe_name

    if dataset_dir is None:
        event_description, time_window, evidence_pool = load_demo_inputs(
            defaults.get("event_path", "examples/demo_event.json"),
            defaults.get("evidence_path", "examples/demo_evidence.jsonl"),
        )
        gold_path = defaults.get("gold_path", "data/pubevent_soa_lite/gold_tuples.jsonl")
    else:
        event_description, time_window, evidence_pool, gold_path = load_dataset(dataset_dir, config)

    configure_logging(resolved_run_dir / "run.log")
    pipeline_config = _pipeline_config_for_setting(config, setting_name)
    run_context = RunContext(
        run_id=f"{resolved_run_dir.name}-{safe_name}",
        run_dir=resolved_run_dir,
        config_path=resolved_run_dir / "metrics" / "ablations" / f"{safe_name}.config.yaml",
        predictions_path=prediction_path,
        metrics_path=metrics_path,
        log_path=resolved_run_dir / "run.log",
        prompts_dir=prompts_dir,
    )
    run_pipeline(
        event_description,
        time_window,
        config=pipeline_config,
        evidence_pool=evidence_pool,
        output_path=prediction_path,
        run_context=run_context,
    )
    evaluate_jsonl(
        prediction_path,
        gold_path,
        metrics_path,
        k=int(defaults.get("metrics_k", 5)),
    )
    print(f"[ablation:{setting_name}] predictions={prediction_path} metrics={metrics_path}")
    return prediction_path, metrics_path


def run_ablations(
    config: dict[str, Any],
    setting: str = "all",
    *,
    dataset_dir: str | Path | None = None,
    seed: int | None = None,
    run_dir: str | Path | None = None,
) -> dict[str, dict[str, str]]:
    if seed is not None:
        set_random_seed(seed)
    resolved_run_dir = resolve_run_dir(run_dir)

    settings = config.get("settings", {})
    if setting != "all" and setting not in settings:
        known = ", ".join(sorted(settings))
        raise ValueError(f"Unknown ablation setting '{setting}'. Expected one of: {known}")

    selected = list(settings) if setting == "all" else [setting]
    outputs: dict[str, dict[str, str]] = {}
    for setting_name in selected:
        prediction_path, metrics_path = run_ablation_setting(
            config,
            setting_name,
            dataset_dir=dataset_dir,
            run_dir=resolved_run_dir,
        )
        outputs[setting_name] = {
            "prediction_path": str(prediction_path),
            "metrics_path": str(metrics_path),
        }

    summary_json_path = resolved_run_dir / "metrics" / "ablations" / "summary.json"
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_json_path.open("w", encoding="utf-8") as file:
        json.dump(outputs, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    write_ablation_summary_csv(resolved_run_dir / "ablation_summary.csv", outputs)
    return outputs


def resolve_run_dir(run_dir: str | Path | None = None) -> Path:
    """Resolve the run directory, defaulting to outputs/latest_run.txt."""
    if run_dir is not None:
        resolved = Path(run_dir)
    else:
        latest_path = Path("outputs/latest_run.txt")
        if not latest_path.exists():
            raise FileNotFoundError("outputs/latest_run.txt not found; pass --run-dir or run run_experiment.py first")
        resolved = Path(latest_path.read_text(encoding="utf-8").strip())
    resolved.mkdir(parents=True, exist_ok=True)
    (resolved / "predictions" / "ablations").mkdir(parents=True, exist_ok=True)
    (resolved / "metrics" / "ablations").mkdir(parents=True, exist_ok=True)
    return resolved


def load_dataset(dataset_dir: str | Path, config: dict[str, Any]) -> tuple[str, dict[str, Any], list[EvidenceRecord], Path]:
    """Load an ablation dataset directory."""
    dataset_path = Path(dataset_dir)
    dataset_config = config.get("dataset", {})
    event_path = dataset_path / dataset_config.get("event_file", "events.jsonl")
    evidence_path = dataset_path / dataset_config.get("evidence_file", "evidence.jsonl")
    gold_path = dataset_path / dataset_config.get("gold_tuple_file", "gold_tuples.jsonl")

    events = _load_jsonl(event_path)
    if not events:
        raise ValueError(f"No events found in {event_path}")
    event_description = str(events[0].get("target_event") or events[0].get("event_description") or "")
    if not event_description:
        raise ValueError("First event must include target_event or event_description")
    time_window = dict(events[0].get("time_window", {}))

    evidence_pool: list[EvidenceRecord] = []
    for row in _load_jsonl(evidence_path):
        evidence_row = dict(row)
        evidence_row.pop("event_id", None)
        evidence_pool.append(EvidenceRecord.model_validate(evidence_row))

    return event_description, time_window, evidence_pool, gold_path


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_ablation_summary_csv(summary_path: Path, outputs: dict[str, dict[str, str]]) -> Path:
    """Write one CSV row per ablation setting with metric columns."""
    rows: list[dict[str, Any]] = []
    fieldnames = ["setting", "prediction_path", "metrics_path"]
    for setting_name, paths in outputs.items():
        metrics = json.loads(Path(paths["metrics_path"]).read_text(encoding="utf-8"))
        for metric_name in metrics:
            if metric_name not in fieldnames:
                fieldnames.append(metric_name)
        rows.append({"setting": setting_name, **paths, **metrics})

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return summary_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA ablation experiments.")
    parser.add_argument("--dataset", help="Dataset directory, e.g. data/pubevent_soa_lite.")
    parser.add_argument("--config", default="configs/ablation.yaml", help="Ablation YAML config path.")
    parser.add_argument("--setting", default="all", help="Ablation setting name, or 'all'.")
    parser.add_argument("--seed", type=int, help="Random seed for reproducible ablations.")
    parser.add_argument("--run-dir", help="Existing outputs/runs/{run_id} directory. Defaults to outputs/latest_run.txt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    dataset_dir = args.dataset or str(Path(config["data"]["event_query_path"]).parent)
    seed = args.seed if args.seed is not None else int(config["seed"])
    run_ablations(config, args.setting, dataset_dir=dataset_dir, seed=seed, run_dir=args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
