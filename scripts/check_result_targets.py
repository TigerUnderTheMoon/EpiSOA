"""Guard experiment outputs before spending full ablation API budget.

This script is intentionally read-only: it validates existing artifacts and
fails fast when the current results do not support a full rerun or paper claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


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
FINAL_BEST_CHECK_METRICS = (
    "Tuple-F1-semantic@0.5",
)
MAIN_TARGET_METRICS = (
    "Tuple-F1-semantic",
    "Tuple-Precision-semantic",
    "Tuple-Recall-semantic",
)
MAIN_TARGET = 0.0


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
    elif mode == "consistency":
        _check_consistency(runs_dir, result, issues)
        _check_iaa_integrity(result, issues)
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
        if metric == "Tuple-F1-semantic@0.5" and full_value <= no_graph_value:
            issues.append(
                f"full_soe must beat without_soe_graph on {metric} before full run: "
                f"{full_value:.4f} <= {no_graph_value:.4f}"
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

    ignored = sorted(
        {
            setting
            for setting in settings
            if setting in ORACLE_SETTINGS or setting in _full_soe_equivalent_aliases(summary)
        }
    )
    result["ignored_settings_for_best_check"] = ignored

    full_metrics = _load_setting_metrics(runs_dir / "ablation_full_soe", "full_soe", issues)
    if full_metrics is None:
        return

    for setting in settings:
        if setting == "full_soe" or setting in ORACLE_SETTINGS:
            continue
        if setting in ignored:
            continue
        setting_metrics = _load_setting_metrics(runs_dir / f"ablation_{setting}", setting, issues)
        if setting_metrics is None:
            continue
        for metric in FINAL_BEST_CHECK_METRICS:
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


def _full_soe_equivalent_aliases(summary: dict[str, Any]) -> set[str]:
    reuse = summary.get("reuse", {}) if isinstance(summary, dict) else {}
    if not isinstance(reuse, dict):
        return set()
    aliases: set[str] = set()
    for setting, payload in reuse.items():
        if not isinstance(payload, dict):
            continue
        if str(setting) == "without_soe_graph":
            continue
        if payload.get("source_setting") == "full_soe" and payload.get("reason") == "same_setting_fingerprint":
            aliases.add(str(setting))
    return aliases


def _load_setting_metrics(setting_dir: Path, setting: str, issues: list[str]) -> dict[str, Any] | None:
    for artifact in REQUIRED_SETTING_ARTIFACTS:
        path = setting_dir / artifact
        if not path.exists():
            issues.append(f"{setting} missing required artifact: {path}")
    _check_setting_attribution_health(setting_dir, setting, issues)
    metrics = _read_json(setting_dir / "metrics.json", issues)
    if not isinstance(metrics, dict):
        return None
    if metrics.get("Metric-Scope") != "gold_event_scope":
        issues.append(f"{setting} Metric-Scope must be gold_event_scope, got {metrics.get('Metric-Scope')}")
    return metrics


def _check_setting_attribution_health(setting_dir: Path, setting: str, issues: list[str]) -> None:
    summary_path = setting_dir / "schema_attribution_summary.json"
    if not summary_path.exists():
        return
    summary = _read_json(summary_path, issues)
    if not isinstance(summary, dict):
        return
    api_calls = _int_value(summary.get("num_api_calls"))
    tuples = _int_value(summary.get("num_tuples_generated"))
    requested = _int_value(summary.get("num_events_requested"))
    skipped = _int_value(summary.get("num_events_skipped"))
    parse_failed = summary.get("parse_failed_events", [])
    parse_failed_count = len(parse_failed) if isinstance(parse_failed, list) else 0
    prompted = max(0, requested - skipped)
    if api_calls > 0 and tuples == 0 and prompted > 0 and parse_failed_count >= prompted:
        issues.append(
            f"{setting} produced zero parsed attribution tuples after {api_calls} API calls "
            f"({parse_failed_count}/{prompted} prompted events parse failed)"
        )


def _check_consistency(runs_dir: Path, result: dict[str, Any], issues: list[str]) -> None:
    """Assert the manuscript's headline numbers match the canonical artifacts.

    Guards against the regression where the docx Table 5/6 carried stale
    pre-remediation numbers (44 tuples / F1=0.1468) while the abstract and
    ablation_summary.json used current numbers (82 tuples / F1@0.3=0.3906).
    The single source of truth is ``ablation_full_soe/metrics.json``.
    """
    full_soe = runs_dir / "ablation_full_soe" / "metrics.json"
    metrics = _read_json(full_soe, issues)
    if not isinstance(metrics, dict):
        return

    # Headline values the abstract / body / Table 5 must agree on.
    expected = {
        "Num-Tuples": metrics.get("Num-Tuples"),
        "Num-Gold": metrics.get("Num-Gold"),
        "Tuple-F1-semantic@0.3": metrics.get("Tuple-F1-semantic@0.3"),
        "Tuple-F1-semantic@0.5": metrics.get("Tuple-F1-semantic@0.5"),
        "Tuple-F1-exact": metrics.get("Tuple-F1-exact"),
        "ESR": metrics.get("ESR"),
    }
    result["comparisons"]["headline_metrics"] = expected

    for key, value in expected.items():
        if value in (None, ""):
            issues.append(f"ablation_full_soe metrics.json missing headline key: {key}")

    # The legacy main run dir (pubevent-soa-lite-human-gold-v2-paper) holds
    # pre-remediation stale metrics. The builder prefers ablation_full_soe, so
    # the legacy file is only a problem if ablation_full_soe is missing (forcing
    # fallback). Record its staleness as info either way.
    legacy_main = runs_dir / "pubevent-soa-lite-human-gold-v2-paper" / "metrics.json"
    if legacy_main.exists():
        legacy = _read_json(legacy_main, [])
        if isinstance(legacy, dict):
            legacy_tuples = legacy.get("Num-Tuples")
            if legacy_tuples is not None and legacy_tuples != expected["Num-Tuples"]:
                if not (runs_dir / "ablation_full_soe" / "metrics.json").exists():
                    issues.append(
                        f"stale legacy main run {legacy_main} has Num-Tuples={legacy_tuples} "
                        f"but canonical ablation_full_soe is missing; builder would fall back to stale"
                    )
                result.setdefault("warnings", []).append(
                    f"legacy main run {legacy_main} is stale (Num-Tuples={legacy_tuples}); "
                    "builder prefers ablation_full_soe, but consider regenerating or removing"
                )

    # ablation_summary.json main_result must agree with ablation_full_soe metrics.
    summary_path = runs_dir / "ablation_summary.json"
    summary = _read_json(summary_path, issues)
    if isinstance(summary, dict):
        main_result = summary.get("main_result") or {}
        if isinstance(main_result, dict):
            for key in ("setting", "tuples", "f1_semantic_03"):
                if key not in main_result:
                    issues.append(f"ablation_summary.json main_result missing key: {key}")
            if main_result.get("tuples") is not None and main_result["tuples"] != expected["Num-Tuples"]:
                issues.append(
                    f"ablation_summary.json main_result.tuples={main_result['tuples']} "
                    f"!= ablation_full_soe Num-Tuples={expected['Num-Tuples']}"
                )
            summary_f1 = main_result.get("f1_semantic_03")
            canonical_f1 = expected["Tuple-F1-semantic@0.3"]
            if summary_f1 is not None and canonical_f1 is not None:
                if abs(float(summary_f1) - float(canonical_f1)) > 1e-6:
                    issues.append(
                        f"ablation_summary.json main_result.f1_semantic_03={summary_f1} "
                        f"!= ablation_full_soe Tuple-F1-semantic@0.3={canonical_f1}"
                    )

    # Significance report must be regenerated from real data, not the hardcoded
    # placeholder that claimed full_soe is +0.0602 better (it is in fact worse).
    sig_path = runs_dir.parent / "manuscript" / "significance_report.json"
    sig = _read_json(sig_path, [])
    if isinstance(sig, dict):
        for comp in sig.get("comparisons", []) or []:
            if not isinstance(comp, dict):
                continue
            if comp.get("baseline") == "full_soe" and comp.get("variant") == "without_decomposed_verifier":
                delta = comp.get("mean_delta")
                if isinstance(delta, (int, float)) and delta > 0:
                    issues.append(
                        f"significance_report.json still has reversed delta (full_soe better by {delta}); "
                        "real data shows full_soe is significantly worse — regenerate"
                    )
                if comp.get("n_events") == 40:
                    issues.append(
                        "significance_report.json still has hardcoded n_events=40; "
                        "real paired event count is ~45 — regenerate"
                    )


def _check_iaa_integrity(result: dict[str, Any], issues: list[str]) -> None:
    """Detect the tautological IAA artifact: annotator_A/B/C sheets identical.

    The bundled independent_audit IAA report claims Fleiss kappa=1.0 / 0
    conflicts, but the three independent sheets are byte-identical copies of
    the post-adjudication gold. Real IAA requires genuine disagreement. This
    flags the artifact so the manuscript does not cite kappa=1.0 as evidence.
    """
    import csv as _csv

    base = ROOT / "data" / "pubevent_soa_lite" / "human_gold_v2_stakeholder_canonical" / "independent"
    report_path = ROOT / "data" / "pubevent_soa_lite" / "human_gold_v2" / "independent_audit" / "independent_annotation_iaa_report.json"
    sheets: dict[str, list[dict[str, str]]] = {}
    for name in ("A", "B", "C"):
        for fname in (f"human{name}_tuple_adjudication_sheet.csv", "humanA_tuple_adjudication_sheet.csv"):
            path = base / f"annotator_{name}" / fname
            if path.exists():
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    sheets[name] = list(_csv.DictReader(handle))
                break
    if len(sheets) < 3:
        result["iaa"] = {"status": "sheets_missing", "found": sorted(sheets)}
        return
    a, b, c = sheets["A"], sheets["B"], sheets["C"]
    iaa_fields = ("stakeholder", "opinion", "sentiment", "rationale")
    n = min(len(a), len(b), len(c))
    field_diffs = 0
    for i in range(n):
        for fld in iaa_fields:
            av = (a[i].get(fld) or "").strip()
            bv = (b[i].get(fld) or "").strip()
            cv = (c[i].get(fld) or "").strip()
            if av != bv or av != cv or bv != cv:
                field_diffs += 1
    identical = field_diffs == 0
    result["iaa"] = {
        "annotator_rows": {k: len(v) for k, v in sheets.items()},
        "iaa_field_diffs": field_diffs,
        "iaa_fields_identical": identical,
        "bundled_kappa": None,
    }
    bundled = _read_json(report_path, [])
    if isinstance(bundled, dict):
        kappa = (bundled.get("tuple_iaa") or {}).get("fleiss_kappa")
        result["iaa"]["bundled_kappa"] = kappa
        if identical and kappa == 1.0:
            issues.append(
                "IAA artifact: annotator_A/B/C sheets have 0 field-level diffs across "
                "stakeholder/opinion/sentiment/rationale but bundled report claims "
                "Fleiss kappa=1.0 — not a valid inter-annotator agreement; do not "
                "cite kappa=1.0 in the manuscript"
            )


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
    parser.add_argument("--mode", choices=("stage-guard", "final", "consistency"), required=True)
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
