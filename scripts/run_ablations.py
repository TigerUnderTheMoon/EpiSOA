"""Run paper ablation experiments for EpiSOA."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from episoa.config import AblationConfig, ExperimentConfig, load_experiment_config
from episoa.pipeline import run_pipeline


REQUIRED_ABLATIONS = {
    "without_fsm": {"disable_fsm": True},
    "without_diversity": {"disable_diversity": True},
    "without_graph": {"disable_graph": True},
    "without_event_chain": {"disable_event_chain": True},
    "without_verifier": {"disable_verifier": True},
    "without_temporal_edges": {"disable_temporal_edges": True},
    "without_stakeholder_constraint": {"disable_stakeholder_constraint": True},
}


def run_ablations(config: ExperimentConfig) -> dict[str, dict[str, str]]:
    """Run each configured ablation into outputs/runs/{run_id}/ablations/{name}/."""
    config.validate_mode_requirements()
    root_run_dir = Path(config.output.run_dir)
    root_run_dir.mkdir(parents=True, exist_ok=True)
    settings = _ablation_settings(config)
    outputs: dict[str, dict[str, str]] = {}

    for name, ablation in settings.items():
        method_dir = root_run_dir / "ablations" / name
        variant = config.model_copy(deep=True)
        variant.run_id = f"{config.run_id}-{name}"
        variant.mode = "ablation"
        variant.ablation = ablation
        variant.output.run_dir = str(method_dir)
        result = run_pipeline(variant)
        outputs[name] = {
            "predictions_path": str(result.predictions_path),
            "metrics_path": str(result.run_dir / "metrics.json"),
        }
        print(f"[ablation:{name}] predictions={result.predictions_path} metrics={result.run_dir / 'metrics.json'}")

    _write_json(root_run_dir / "ablation_summary.json", outputs)
    _write_csv(root_run_dir / "ablation_summary.csv", "ablation", outputs)
    return outputs


def _ablation_settings(config: ExperimentConfig) -> dict[str, AblationConfig]:
    if config.ablation_settings:
        return config.ablation_settings
    return {name: AblationConfig.model_validate(flags) for name, flags in REQUIRED_ABLATIONS.items()}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, label: str, outputs: dict[str, dict[str, str]]) -> None:
    rows: list[dict[str, Any]] = []
    fieldnames = [label, "predictions_path", "metrics_path"]
    for name, paths in outputs.items():
        metrics = json.loads(Path(paths["metrics_path"]).read_text(encoding="utf-8"))
        for metric_name in metrics:
            if metric_name not in fieldnames:
                fieldnames.append(metric_name)
        rows.append({label: name, **paths, **metrics})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA paper ablations.")
    parser.add_argument("--config", default="configs/ablation.yaml", help="Ablation YAML config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_ablations(load_experiment_config(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
