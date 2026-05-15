"""Ablation delta and reproducibility audit helpers."""

from __future__ import annotations

from collections import defaultdict
import csv
import json
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl
from episoa.evaluation.metrics import soft_tuple_f1


CHAIN_ABLATION_SETTINGS = [
    "without_event_chain",
    "without_event_chain_prompt",
    "without_event_chain_ranking",
]

DELTA_FIELDNAMES = [
    "event_id",
    "gold_tuple_count",
    "full_pred_count",
    "ablation_pred_count",
    "full_matched_count",
    "ablation_matched_count",
    "full_precision",
    "full_recall",
    "ablation_precision",
    "ablation_recall",
    "full_selected_evidence_ids",
    "ablation_selected_evidence_ids",
    "evidence_overlap_ratio",
    "full_prompt_chars",
    "ablation_prompt_chars",
    "full_parse_success",
    "ablation_parse_success",
    "delta_reason",
]


def write_ablation_delta_audits(
    *,
    runs_dir: str | Path,
    gold_tuples: list[Any],
    output_dir: str | Path | None = None,
    settings: list[str] | None = None,
) -> dict[str, Path]:
    runs_path = Path(runs_dir)
    delta_dir = Path(output_dir) if output_dir is not None else runs_path / "ablation_delta"
    delta_dir.mkdir(parents=True, exist_ok=True)

    full_dir = runs_path / "ablation_full"
    full_data = _load_setting_data(full_dir)
    gold_by_event = _group_by_event(gold_tuples)
    output_paths: dict[str, Path] = {}

    for setting in settings or CHAIN_ABLATION_SETTINGS:
        ablation_dir = runs_path / f"ablation_{setting}"
        if not ablation_dir.exists():
            continue
        rows = _delta_rows(
            gold_by_event=gold_by_event,
            full_data=full_data,
            ablation_data=_load_setting_data(ablation_dir),
        )
        path = delta_dir / f"full_vs_{setting}.csv"
        _write_csv(path, rows, DELTA_FIELDNAMES)
        output_paths[setting] = path
    return output_paths


def write_ablation_audit_report(
    *,
    runs_dir: str | Path,
    settings: list[str],
    flags_by_setting: dict[str, dict[str, Any]],
    output_path: str | Path | None = None,
) -> Path:
    runs_path = Path(runs_dir)
    report_path = Path(output_path) if output_path is not None else runs_path / "ablation_audit_report.md"
    metrics_by_setting = {
        setting: _read_json(runs_path / f"ablation_{setting}" / "metrics.json")
        for setting in settings
        if (runs_path / f"ablation_{setting}" / "metrics.json").exists()
    }
    manifests = {
        setting: _read_json(runs_path / f"ablation_{setting}" / "input_manifest.json")
        for setting in settings
        if (runs_path / f"ablation_{setting}" / "input_manifest.json").exists()
    }
    artifact_status = {
        setting: _setting_artifact_status(runs_path / f"ablation_{setting}")
        for setting in settings
    }
    event_sets = {
        setting: _event_ids_from_event_metrics(runs_path / f"ablation_{setting}" / "event_level_metrics.csv")
        for setting in settings
    }
    delta_summaries = {
        setting: _summarize_delta_csv(runs_path / "ablation_delta" / f"full_vs_{setting}.csv")
        for setting in CHAIN_ABLATION_SETTINGS
    }

    lines: list[str] = []
    lines.append("# Ablation Audit Report")
    lines.append("")
    lines.append("## Settings")
    for setting in settings:
        lines.append(f"### {setting}")
        lines.append(f"- flags: `{json.dumps(flags_by_setting.get(setting, {}), ensure_ascii=False, sort_keys=True)}`")
        manifest = manifests.get(setting, {})
        data = manifest.get("data", {})
        model = manifest.get("model", {})
        lines.append(f"- events_path: `{data.get('events_path', '')}`")
        lines.append(f"- evidence_path: `{data.get('evidence_path', '')}`")
        lines.append(f"- gold_tuples_path: `{data.get('gold_tuples_path', '')}`")
        lines.append(f"- gold_event_chains_path: `{data.get('gold_event_chains_path', '')}`")
        lines.append(
            "- model: "
            f"`{model.get('model_name', '')}`, base_url=`{model.get('base_url', '')}`, "
            f"temperature=`{model.get('temperature', '')}`, max_tokens=`{model.get('max_tokens', '')}`"
        )
        lines.append("")

    lines.append("## Metrics")
    metric_columns = [
        "Num-Gold",
        "Num-Tuples",
        "Tuple-F1-soft",
        "Tuple-Precision",
        "Tuple-Recall",
        "Sentiment-Acc",
        "Stakeholder-Recall",
        "ESR",
        "UTR",
        "Candidate-UTR",
    ]
    lines.append("| Setting | " + " | ".join(metric_columns) + " |")
    lines.append("|---|" + "|".join(["---"] * len(metric_columns)) + "|")
    for setting in settings:
        metrics = metrics_by_setting.get(setting, {})
        values = [_format_metric(metrics.get(column, "")) for column in metric_columns]
        lines.append(f"| {setting} | " + " | ".join(values) + " |")
    lines.append("")

    checks = _audit_checks(settings, metrics_by_setting, artifact_status, event_sets)
    lines.append("## Reproducibility Checks")
    for check in checks:
        lines.append(f"- {check}")
    lines.append("")

    lines.append("## Delta Interpretation")
    lines.extend(_interpret_chain_deltas(metrics_by_setting, delta_summaries))
    lines.append("")

    usable = all(check.startswith("PASS") for check in checks)
    lines.append("## Paper Table Judgment")
    if usable:
        lines.append("The ablation table is usable for the paper based on the current artifacts and reproducibility checks.")
    else:
        lines.append("The ablation table is not paper-ready until the failed reproducibility checks above are fixed.")
    lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _delta_rows(
    *,
    gold_by_event: dict[str, list[Any]],
    full_data: dict[str, dict[str, Any]],
    ablation_data: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    event_ids = sorted(set(gold_by_event) | set(full_data["predictions"]) | set(ablation_data["predictions"]))
    rows: list[dict[str, Any]] = []
    for event_id in event_ids:
        gold = gold_by_event.get(event_id, [])
        full_predictions = full_data["predictions"].get(event_id, [])
        ablation_predictions = ablation_data["predictions"].get(event_id, [])
        full_metrics = soft_tuple_f1(gold, full_predictions, threshold=0.5)
        ablation_metrics = soft_tuple_f1(gold, ablation_predictions, threshold=0.5)
        full_raw = full_data["raw"].get(event_id, {})
        ablation_raw = ablation_data["raw"].get(event_id, {})
        full_summary = full_raw.get("request_summary", {}) if isinstance(full_raw, dict) else {}
        ablation_summary = ablation_raw.get("request_summary", {}) if isinstance(ablation_raw, dict) else {}
        full_evidence = [str(item) for item in full_summary.get("selected_evidence_ids", [])]
        ablation_evidence = [str(item) for item in ablation_summary.get("selected_evidence_ids", [])]
        rows.append(
            {
                "event_id": event_id,
                "gold_tuple_count": len(gold),
                "full_pred_count": len(full_predictions),
                "ablation_pred_count": len(ablation_predictions),
                "full_matched_count": int(full_metrics["true_positives"]),
                "ablation_matched_count": int(ablation_metrics["true_positives"]),
                "full_precision": full_metrics["precision"],
                "full_recall": full_metrics["recall"],
                "ablation_precision": ablation_metrics["precision"],
                "ablation_recall": ablation_metrics["recall"],
                "full_selected_evidence_ids": "|".join(full_evidence),
                "ablation_selected_evidence_ids": "|".join(ablation_evidence),
                "evidence_overlap_ratio": _overlap_ratio(full_evidence, ablation_evidence),
                "full_prompt_chars": int(full_summary.get("prompt_chars", 0) or 0),
                "ablation_prompt_chars": int(ablation_summary.get("prompt_chars", 0) or 0),
                "full_parse_success": full_raw.get("parse_success", ""),
                "ablation_parse_success": ablation_raw.get("parse_success", ""),
                "delta_reason": _delta_reason(
                    full_metrics=full_metrics,
                    ablation_metrics=ablation_metrics,
                    full_evidence=full_evidence,
                    ablation_evidence=ablation_evidence,
                    full_raw=full_raw,
                    ablation_raw=ablation_raw,
                ),
            }
        )
    return rows


def _load_setting_data(setting_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        "predictions": _group_by_event(read_jsonl(setting_dir / "predictions.jsonl") if (setting_dir / "predictions.jsonl").exists() else []),
        "raw": {
            str(row.get("event_id", "")): row
            for row in (read_jsonl(setting_dir / "raw_llm_responses.jsonl") if (setting_dir / "raw_llm_responses.jsonl").exists() else [])
        },
    }


def _group_by_event(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        if isinstance(row, dict):
            event_id = str(row.get("event_id", ""))
        else:
            event_id = str(getattr(row, "event_id", ""))
        grouped[event_id].append(row)
    return dict(grouped)


def _overlap_ratio(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 1.0
    return round(len(left_set & right_set) / len(union), 4)


def _delta_reason(
    *,
    full_metrics: dict[str, Any],
    ablation_metrics: dict[str, Any],
    full_evidence: list[str],
    ablation_evidence: list[str],
    full_raw: dict[str, Any],
    ablation_raw: dict[str, Any],
) -> str:
    full_tp = int(full_metrics.get("true_positives", 0))
    ablation_tp = int(ablation_metrics.get("true_positives", 0))
    if full_raw.get("parse_success") is False and ablation_raw.get("parse_success") is True:
        return "full_parse_failed"
    if full_raw.get("parse_success") is True and ablation_raw.get("parse_success") is False:
        return "ablation_parse_failed"
    if set(full_evidence) != set(ablation_evidence):
        if ablation_tp > full_tp:
            return "evidence_selection_improved_ablation"
        if ablation_tp < full_tp:
            return "evidence_selection_hurt_ablation"
        return "evidence_selection_changed_no_match_delta"
    if ablation_tp > full_tp:
        return "prompt_changed_improved_ablation"
    if ablation_tp < full_tp:
        return "prompt_changed_hurt_ablation"
    return "no_tuple_match_delta"


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _setting_artifact_status(setting_dir: Path) -> dict[str, bool]:
    return {
        name: (setting_dir / name).exists()
        for name in ("metrics.json", "predictions.jsonl", "raw_llm_responses.jsonl", "event_level_metrics.csv")
    }


def _event_ids_from_event_metrics(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["event_id"] for row in csv.DictReader(handle) if row.get("event_id")}


def _summarize_delta_csv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"exists": True, "num_events": 0}
    improved = [row for row in rows if int(row.get("ablation_matched_count", 0)) > int(row.get("full_matched_count", 0))]
    hurt = [row for row in rows if int(row.get("ablation_matched_count", 0)) < int(row.get("full_matched_count", 0))]
    avg_overlap = sum(float(row.get("evidence_overlap_ratio", 0) or 0) for row in rows) / len(rows)
    reason_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        reason_counts[row.get("delta_reason", "")] += 1
    return {
        "exists": True,
        "num_events": len(rows),
        "improved_events": len(improved),
        "hurt_events": len(hurt),
        "avg_overlap": round(avg_overlap, 4),
        "reason_counts": dict(reason_counts),
    }


def _audit_checks(
    settings: list[str],
    metrics_by_setting: dict[str, dict[str, Any]],
    artifact_status: dict[str, dict[str, bool]],
    event_sets: dict[str, set[str]],
) -> list[str]:
    checks: list[str] = []
    missing_artifacts = [
        f"{setting}:{name}"
        for setting in settings
        for name, exists in artifact_status.get(setting, {}).items()
        if not exists
    ]
    checks.append("PASS artifacts exist for every setting" if not missing_artifacts else f"FAIL missing artifacts: {', '.join(missing_artifacts)}")

    num_gold_values = {metrics.get("Num-Gold") for metrics in metrics_by_setting.values()}
    checks.append("PASS Num-Gold is identical across settings" if len(num_gold_values) == 1 else f"FAIL Num-Gold differs: {sorted(num_gold_values)}")

    non_empty_event_sets = [events for events in event_sets.values() if events]
    same_events = bool(non_empty_event_sets) and all(events == non_empty_event_sets[0] for events in non_empty_event_sets)
    checks.append("PASS event_id sets are identical across settings" if same_events else "FAIL event_id sets differ or are missing")

    without_verifier = metrics_by_setting.get("without_verifier", {})
    esr = without_verifier.get("ESR")
    checks.append("PASS without_verifier ESR is N/A/null" if esr is None else f"FAIL without_verifier ESR is {esr}")
    if "Candidate-UTR" in without_verifier and without_verifier.get("UTR") is None:
        checks.append("PASS without_verifier uses Candidate-UTR instead of verifier UTR")
    else:
        checks.append("FAIL without_verifier Candidate-UTR/UTR separation is missing")
    return checks


def _interpret_chain_deltas(
    metrics_by_setting: dict[str, dict[str, Any]],
    delta_summaries: dict[str, dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    full_f1 = _safe_float(metrics_by_setting.get("full", {}).get("Tuple-F1-soft"))
    without_chain_f1 = _safe_float(metrics_by_setting.get("without_event_chain", {}).get("Tuple-F1-soft"))
    if without_chain_f1 > full_f1:
        summary = delta_summaries.get("without_event_chain", {})
        lines.append(
            "- `without_event_chain` remains higher than `full`; this should be treated as an architecture/evidence-selection finding, not as a direct model conclusion."
        )
        lines.append(f"- Delta summary: `{json.dumps(summary, ensure_ascii=False, sort_keys=True)}`")
    else:
        lines.append("- `without_event_chain` is not higher than `full` in this run.")

    prompt_summary = delta_summaries.get("without_event_chain_prompt", {})
    ranking_summary = delta_summaries.get("without_event_chain_ranking", {})
    prompt_f1 = _safe_float(metrics_by_setting.get("without_event_chain_prompt", {}).get("Tuple-F1-soft"))
    ranking_f1 = _safe_float(metrics_by_setting.get("without_event_chain_ranking", {}).get("Tuple-F1-soft"))
    if prompt_f1 > full_f1:
        lines.append(f"- Chain prompt information is a likely noise source; prompt-only delta summary: `{json.dumps(prompt_summary, ensure_ascii=False, sort_keys=True)}`")
    if ranking_f1 > full_f1:
        lines.append(f"- Chain-based ranking is a likely evidence-selection issue; ranking delta summary: `{json.dumps(ranking_summary, ensure_ascii=False, sort_keys=True)}`")
    if prompt_f1 <= full_f1 and ranking_f1 <= full_f1 and without_chain_f1 > full_f1:
        lines.append("- The gain appears only when retrieval, ranking, and prompt chain information are all removed; inspect per-event evidence overlap before attributing it to one isolated component.")
    if not lines:
        lines.append("- No chain-ablation delta interpretation is available.")
    return lines


def _format_metric(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
