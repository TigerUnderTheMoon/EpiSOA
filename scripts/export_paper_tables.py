"""Export paper-ready CSV tables from EpiSOA run metrics."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from episoa.evaluation.metrics import PAPER_METRIC_KEYS, ensure_paper_metric_keys


def export_paper_tables(runs_dir: str | Path, output: str | Path) -> dict[str, Path]:
    runs_path = Path(runs_dir)
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    main_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    ablation_rows: list[dict[str, Any]] = []

    for run_dir in sorted(path for path in runs_path.iterdir() if path.is_dir()):
        main_metrics = run_dir / "metrics.json"
        if main_metrics.exists() and (run_dir / "summary.json").exists():
            main_rows.append(_metric_row(run_dir.name, "episoa_full", main_metrics))

        if (run_dir / "baselines").exists():
            for metrics_path in sorted((run_dir / "baselines").glob("*/metrics.json")):
                baseline_rows.append(_metric_row(run_dir.name, metrics_path.parent.name, metrics_path))

        if (run_dir / "ablations").exists():
            for metrics_path in sorted((run_dir / "ablations").glob("*/metrics.json")):
                ablation_rows.append(_metric_row(run_dir.name, metrics_path.parent.name, metrics_path))

    paths = {
        "main_results": output_path / "main_results.csv",
        "baseline_results": output_path / "baseline_results.csv",
        "ablation_results": output_path / "ablation_results.csv",
    }
    _write_table(paths["main_results"], ["run_id", "method", *PAPER_METRIC_KEYS], main_rows)
    _write_table(paths["baseline_results"], ["run_id", "method", *PAPER_METRIC_KEYS], baseline_rows)
    _write_table(paths["ablation_results"], ["run_id", "method", *PAPER_METRIC_KEYS], ablation_rows)
    return paths


def _metric_row(run_id: str, method: str, metrics_path: Path) -> dict[str, Any]:
    metrics = ensure_paper_metric_keys(json.loads(metrics_path.read_text(encoding="utf-8")))
    return {"run_id": run_id, "method": method, **{key: metrics[key] for key in PAPER_METRIC_KEYS}}


def _write_table(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export EpiSOA paper result tables.")
    parser.add_argument("--runs-dir", "--runs_dir", dest="runs_dir", default="outputs/runs")
    parser.add_argument("--output", default="outputs/paper_tables")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    paths = export_paper_tables(args.runs_dir, args.output)
    for name, path in paths.items():
        print(f"{name}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
