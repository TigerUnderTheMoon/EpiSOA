"""Build a main experiment vs ablation comparison table."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ORACLE_SETTINGS = {"oracle_evidence", "full_oracle_evidence"}
THRESHOLD_METRICS = (
    ("0.25", "Tuple-F1-semantic@0.25"),
    ("0.3", "Tuple-F1-semantic@0.3"),
    ("0.5", "Tuple-F1-semantic@0.5"),
)
OUTPUT_METRICS = (
    "Metric-Scope",
    "Num-Gold",
    "Num-Tuples",
    "Num-Tuples-All",
    "Tuple-F1-soft",
    "Tuple-F1-char@0.5",
    "Tuple-F1-exact",
    "Tuple-Precision",
    "Tuple-Recall",
    "Tuple-F1-semantic@0.25",
    "Tuple-Precision-semantic@0.25",
    "Tuple-Recall-semantic@0.25",
    "Tuple-F1-semantic@0.3",
    "Tuple-Precision-semantic@0.3",
    "Tuple-Recall-semantic@0.3",
    "Tuple-F1-semantic@0.5",
    "Tuple-Precision-semantic@0.5",
    "Tuple-Recall-semantic@0.5",
    "Stakeholder-Recall",
    "Opinion-Recall",
    "ESR",
    "UTR",
    "Excluded-Predictions",
    "Excluded-Event-Count",
    "Excluded-Event-Ids",
)


def build_comparison(
    *,
    runs_dir: str | Path,
    main_dir: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    runs_dir = Path(runs_dir)
    main_dir = Path(main_dir) if main_dir is not None else runs_dir / "pubevent-soa-lite-human-gold-v2-paper"
    output_path = Path(output_path) if output_path is not None else runs_dir / "main_vs_ablation_comparison.csv"

    issues: list[str] = []
    failures: list[dict[str, Any]] = []
    main_metrics = _read_json(main_dir / "metrics.json", issues)
    if not isinstance(main_metrics, dict):
        return {
            "status": "failed",
            "generation_status": "failed",
            "issues": issues,
            "failures": failures,
            "output_path": str(output_path),
        }

    summary = _read_json(runs_dir / "ablation_summary.json", issues)
    settings = summary.get("settings", []) if isinstance(summary, dict) else []
    if not isinstance(settings, list):
        issues.append("ablation_summary settings is not a list")
        settings = []

    rows: list[dict[str, str]] = []
    rows.append(_main_row(main_metrics))
    for setting in settings:
        metrics = _read_json(runs_dir / f"ablation_{setting}" / "metrics.json", issues)
        if not isinstance(metrics, dict):
            continue
        row, row_failures = _ablation_row(setting, metrics, main_metrics)
        rows.append(row)
        failures.extend(row_failures)

    _write_csv(output_path, rows)
    result = {
        "status": "failed" if issues or failures else "passed",
        "generation_status": "failed" if issues else "passed",
        "issues": issues,
        "failures": failures,
        "output_path": str(output_path),
    }
    (runs_dir / "main_vs_ablation_comparison_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _main_row(metrics: dict[str, Any]) -> dict[str, str]:
    row = {
        "row_type": "main",
        "setting": "main_paper_experiment",
        "comparison_included": "false",
        "verdict": "reference",
    }
    row.update(_metric_cells(metrics))
    for threshold, metric in THRESHOLD_METRICS:
        row[f"delta_F1_semantic@{threshold}_vs_main"] = "0.0000"
        row[f"ge_main_F1_semantic@{threshold}"] = ""
    row["any_threshold_ge_main"] = ""
    return row


def _ablation_row(
    setting: str,
    metrics: dict[str, Any],
    main_metrics: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    included = setting != "full_soe" and setting not in ORACLE_SETTINGS
    row = {
        "row_type": "ablation",
        "setting": setting,
        "comparison_included": "true" if included else "false",
    }
    row.update(_metric_cells(metrics))
    failures: list[dict[str, Any]] = []
    failed_thresholds: list[str] = []
    for threshold, metric in THRESHOLD_METRICS:
        value = _metric_float(metrics, metric)
        main_value = _metric_float(main_metrics, metric)
        if value is None or main_value is None:
            row[f"delta_F1_semantic@{threshold}_vs_main"] = ""
            row[f"ge_main_F1_semantic@{threshold}"] = ""
            continue
        delta = value - main_value
        ge_main = value >= main_value
        row[f"delta_F1_semantic@{threshold}_vs_main"] = f"{delta:.4f}"
        row[f"ge_main_F1_semantic@{threshold}"] = str(ge_main).lower()
        if included and ge_main and threshold == "0.5":
            failed_thresholds.append(threshold)
            failures.append(
                {
                    "setting": setting,
                    "metric": metric,
                    "setting_value": round(value, 4),
                    "main_value": round(main_value, 4),
                    "diff": round(delta, 4),
                }
            )
    row["any_threshold_ge_main"] = str(bool(failed_thresholds)).lower() if included else ""
    if setting == "full_soe":
        row["verdict"] = "not_applicable_full_soe_sanity"
    elif setting in ORACLE_SETTINGS:
        row["verdict"] = "upper_bound_only"
    elif failed_thresholds:
        row["verdict"] = "fail_ge_main_at_" + "|".join(failed_thresholds)
    else:
        row["verdict"] = "pass_below_main_at_0.5"
    return row, failures


def _metric_cells(metrics: dict[str, Any]) -> dict[str, str]:
    return {metric: _format_value(metrics.get(metric, "")) for metric in OUTPUT_METRICS}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    delta_fields: list[str] = []
    for threshold, _metric in THRESHOLD_METRICS:
        delta_fields.append(f"delta_F1_semantic@{threshold}_vs_main")
        delta_fields.append(f"ge_main_F1_semantic@{threshold}")
    fieldnames = [
        "row_type",
        "setting",
        "comparison_included",
        *OUTPUT_METRICS,
        *delta_fields,
        "any_threshold_ge_main",
        "verdict",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_json(path: Path, issues: list[str]) -> Any:
    if not path.exists():
        issues.append(f"missing JSON artifact: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(f"invalid JSON artifact {path}: {exc}")
        return None


def _metric_float(metrics: dict[str, Any], metric: str) -> float | None:
    try:
        return float(metrics[metric])
    except (KeyError, TypeError, ValueError):
        return None


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default="outputs/runs_human_gold_v2")
    parser.add_argument("--main-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_comparison(runs_dir=args.runs_dir, main_dir=args.main_dir, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["generation_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
