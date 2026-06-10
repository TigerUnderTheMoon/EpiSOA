"""Guard experiment outputs before spending full ablation API budget.

This script is intentionally read-only: it validates existing artifacts and
fails fast when the current results do not support a full rerun or paper claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_SETTING_ARTIFACTS = (
    "metrics.json",
    "scoring_scope.json",
    "verified_soa_tuples.jsonl",
    "candidate_soa_tuples.jsonl",
    "metric_threshold_sensitivity.csv",
    "tuple_failure_audit.csv",
)

STAGE_GUARD_SETTINGS = ("full_soe", "without_soe_graph")
ORACLE_SETTINGS = {"oracle_evidence", "full_oracle_evidence"}
BEST_CHECK_METRICS = (
    "Tuple-F1-semantic@0.25",
    "Tuple-F1-semantic@0.3",
    "Tuple-F1-semantic@0.5",
)
MAIN_TARGET_METRICS = (
    "Tuple-F1-semantic",
    "Tuple-Precision-semantic",
    "Tuple-Recall-semantic",
)
MAIN_TARGET = 0.7


def run_gate(
    *,
    runs_dir: str | Path,
    mode: str,
    main_dir: str | Path | None = None,
) -> dict[str, Any]:
    runs_dir = Path(runs_dir)
    issues: list[str] = []
    result: dict[str, Any] = {
        "mode": mode,
        "runs_dir": str(runs_dir),
        "status": "passed",
        "issues": issues,
        "comparisons": {},
    }

    if mode == "stage-guard":
        _check_stage_guard(runs_dir, result, issues)
    elif mode == "final":
        _check_final_gate(runs_dir, Path(main_dir) if main_dir is not None else None, result, issues)
    else:
        issues.append(f"unknown mode: {mode}")

    if issues:
        result["status"] = "failed"
    return result


def _check_stage_guard(runs_dir: Path, result: dict[str, Any], issues: list[str]) -> None:
    metrics_by_setting: dict[str, dict[str, Any]] = {}
    for setting in STAGE_GUARD_SETTINGS:
        setting_dir = runs_dir / f"ablation_{setting}"
        metrics = _load_setting_metrics(setting_dir, setting, issues)
        if metrics is not None:
            metrics_by_setting[setting] = metrics

    if set(metrics_by_setting) != set(STAGE_GUARD_SETTINGS):
        return

    full = metrics_by_setting["full_soe"]
    no_graph = metrics_by_setting["without_soe_graph"]
    comparison: dict[str, float] = {}
    for metric in BEST_CHECK_METRICS:
        full_value = _metric_float(full, metric)
        no_graph_value = _metric_float(no_graph, metric)
        if full_value is None or no_graph_value is None:
            issues.append(f"missing {metric} for full_soe or without_soe_graph")
            continue
        delta = round(full_value - no_graph_value, 4)
        comparison[f"{metric}_delta"] = delta
        if metric == "Tuple-F1-semantic@0.3" and full_value <= no_graph_value:
            issues.append(
                f"full_soe must beat without_soe_graph on {metric} before full run: "
                f"{full_value:.4f} <= {no_graph_value:.4f}"
            )
        if metric == "Tuple-F1-semantic@0.5" and full_value < no_graph_value:
            issues.append(
                f"full_soe regresses below without_soe_graph on {metric}: "
                f"{full_value:.4f} < {no_graph_value:.4f}"
            )
    result["comparisons"]["full_soe_vs_without_soe_graph"] = comparison

    summary = _read_json(runs_dir / "ablation_full_soe" / "schema_attribution_summary.json", issues)
    empty_events = summary.get("empty_tuple_events", []) if isinstance(summary, dict) else []
    if "E046" in [str(event_id) for event_id in empty_events]:
        issues.append("E046 remains in full_soe empty_tuple_events")


def _check_final_gate(
    runs_dir: Path,
    main_dir: Path | None,
    result: dict[str, Any],
    issues: list[str],
) -> None:
    main_dir = main_dir or runs_dir / "pubevent-soa-lite-human-gold-v2-paper"
    main_metrics = _read_json(main_dir / "metrics.json", issues)
    if not isinstance(main_metrics, dict):
        return
    if main_metrics.get("Metric-Scope") != "gold_event_scope":
        issues.append(f"main Metric-Scope must be gold_event_scope, got {main_metrics.get('Metric-Scope')}")

    for metric in MAIN_TARGET_METRICS:
        value = _metric_float(main_metrics, metric)
        if value is None:
            issues.append(f"main metrics missing {metric}")
        elif value <= MAIN_TARGET:
            issues.append(f"main {metric} must be > {MAIN_TARGET:.1f}, got {value:.4f}")

    summary = _read_json(runs_dir / "ablation_summary.json", issues)
    settings = summary.get("settings", []) if isinstance(summary, dict) else []
    if isinstance(summary, dict) and summary.get("status") != "completed":
        issues.append(f"ablation_summary status must be completed, got {summary.get('status')}")
    if not isinstance(settings, list) or not settings:
        issues.append("ablation_summary settings must be a non-empty list")
        return

    ignored = sorted(setting for setting in settings if setting in ORACLE_SETTINGS)
    result["ignored_settings_for_best_check"] = ignored

    full_metrics = _load_setting_metrics(runs_dir / "ablation_full_soe", "full_soe", issues)
    if full_metrics is None:
        return

    for setting in settings:
        if setting == "full_soe" or setting in ORACLE_SETTINGS:
            continue
        setting_metrics = _load_setting_metrics(runs_dir / f"ablation_{setting}", setting, issues)
        if setting_metrics is None:
            continue
        for metric in BEST_CHECK_METRICS:
            full_value = _metric_float(full_metrics, metric)
            setting_value = _metric_float(setting_metrics, metric)
            if full_value is None or setting_value is None:
                issues.append(f"missing {metric} for full_soe or {setting}")
                continue
            if setting_value >= full_value:
                diff = setting_value - full_value
                issues.append(
                    f"{setting} is not below full_soe on {metric}: "
                    f"{setting_value:.4f} >= {full_value:.4f} (diff={diff:.4f})"
                )


def _load_setting_metrics(setting_dir: Path, setting: str, issues: list[str]) -> dict[str, Any] | None:
    for artifact in REQUIRED_SETTING_ARTIFACTS:
        path = setting_dir / artifact
        if not path.exists():
            issues.append(f"{setting} missing required artifact: {path}")
    metrics = _read_json(setting_dir / "metrics.json", issues)
    if not isinstance(metrics, dict):
        return None
    if metrics.get("Metric-Scope") != "gold_event_scope":
        issues.append(f"{setting} Metric-Scope must be gold_event_scope, got {metrics.get('Metric-Scope')}")
    return metrics


def _metric_float(metrics: dict[str, Any], metric: str) -> float | None:
    value = metrics.get(metric)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path, issues: list[str]) -> Any:
    if not path.exists():
        issues.append(f"missing JSON artifact: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(f"invalid JSON artifact {path}: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default="outputs/runs_human_gold_v2")
    parser.add_argument("--mode", choices=("stage-guard", "final"), required=True)
    parser.add_argument("--main-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    result = run_gate(runs_dir=args.runs_dir, mode=args.mode, main_dir=args.main_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
