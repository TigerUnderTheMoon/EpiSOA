#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Select five events for pilot human adjudication."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_COVERAGE = Path("outputs/audit_full_pipeline/evidence_coverage_by_event.csv")
DEFAULT_GOLD_QUALITY = Path("outputs/audit_full_pipeline/gold_quality_by_event.csv")
DEFAULT_MODEL_PROBE = Path("outputs/model_probe/model_capability_probe_results.csv")
DEFAULT_CHAIN_SHEET = Path("data/pubevent_soa_lite/human_gold_v1/human_chain_adjudication_sheet.csv")
DEFAULT_OUTPUT_DIR = Path("data/pubevent_soa_lite/human_gold_v1")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selection = select_pilot_events(
        coverage_path=Path(args.coverage),
        gold_quality_path=Path(args.gold_quality),
        model_probe_path=Path(args.model_probe),
        chain_sheet_path=Path(args.chain_sheet),
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events_out = output_dir / "pilot_events_v1.json"
    report_out = output_dir / "pilot_event_selection_report.md"
    write_json(events_out, selection)
    write_text(report_out, render_report(selection))
    print(json.dumps({
        "pilot_events": [row["event_id"] for row in selection["events"]],
        "events_out": str(events_out),
        "report_out": str(report_out),
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select five events for pilot human review.")
    parser.add_argument("--coverage", default=str(DEFAULT_COVERAGE))
    parser.add_argument("--gold-quality", default=str(DEFAULT_GOLD_QUALITY))
    parser.add_argument("--model-probe", default=str(DEFAULT_MODEL_PROBE))
    parser.add_argument("--chain-sheet", default=str(DEFAULT_CHAIN_SHEET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def select_pilot_events(
    *,
    coverage_path: Path,
    gold_quality_path: Path,
    model_probe_path: Path,
    chain_sheet_path: Path,
) -> dict[str, Any]:
    coverage = {row["event_id"]: row for row in read_csv(coverage_path) if row.get("event_id")}
    gold_quality = {row["event_id"]: row for row in read_csv(gold_quality_path) if row.get("event_id")}
    probe_rows = [row for row in read_csv(model_probe_path) if row.get("scope") == "event" and row.get("event_id")]
    chain_counts = Counter(row.get("event_id") for row in read_csv(chain_sheet_path) if row.get("event_id"))

    selected: list[dict[str, Any]] = []
    used: set[str] = set()

    add_ranked(
        selected,
        used,
        "high_coverage",
        sorted(
            coverage.values(),
            key=lambda row: (as_float(row.get("gold_evidence_in_prompt_ratio")), as_int(row.get("gold_evidence_id_count")), row["event_id"]),
            reverse=True,
        ),
        lambda row: f"highest gold evidence prompt coverage ({as_float(row.get('gold_evidence_in_prompt_ratio')):.4f})",
    )
    add_ranked(
        selected,
        used,
        "low_coverage",
        sorted(
            coverage.values(),
            key=lambda row: (as_float(row.get("gold_evidence_in_prompt_ratio")), -as_int(row.get("gold_evidence_id_count")), row["event_id"]),
        ),
        lambda row: f"lowest gold evidence prompt coverage ({as_float(row.get('gold_evidence_in_prompt_ratio')):.4f})",
    )
    add_ranked(
        selected,
        used,
        "many_tuples",
        sorted(
            gold_quality.values(),
            key=lambda row: (as_int(row.get("gold_tuple_count")), as_int(row.get("unique_gold_evidence_count")), row["event_id"]),
            reverse=True,
        ),
        lambda row: f"largest silver tuple count ({as_int(row.get('gold_tuple_count'))})",
    )

    chain_rows = [{"event_id": event_id, "chain_count": count} for event_id, count in chain_counts.items()]
    add_ranked(
        selected,
        used,
        "many_chains",
        sorted(chain_rows, key=lambda row: (row["chain_count"], row["event_id"]), reverse=True),
        lambda row: f"largest chain count ({row['chain_count']})",
    )
    add_ranked(
        selected,
        used,
        "model_probe_poor",
        sorted(
            probe_rows,
            key=lambda row: (as_float(row.get("Tuple-F1-soft")), -as_int(row.get("zero_pred_count")), row["event_id"]),
        ),
        lambda row: f"model probe poor performance: F1={as_float(row.get('Tuple-F1-soft')):.4f}, zero_pred={as_int(row.get('zero_pred_count'))}",
    )

    if len(selected) != 5:
        raise ValueError(f"expected 5 unique pilot events, got {len(selected)}")

    for item in selected:
        event_id = item["event_id"]
        item["metrics"] = {
            "gold_evidence_in_prompt_ratio": as_float(coverage.get(event_id, {}).get("gold_evidence_in_prompt_ratio")),
            "gold_evidence_in_chain_ratio": as_float(coverage.get(event_id, {}).get("gold_evidence_in_chain_ratio")),
            "gold_tuple_count": as_int(gold_quality.get(event_id, {}).get("gold_tuple_count")),
            "chain_count": int(chain_counts.get(event_id, 0)),
            "model_probe_tuple_f1_soft": probe_metric(probe_rows, event_id, "Tuple-F1-soft"),
            "model_probe_error_category": probe_text(probe_rows, event_id, "error_category"),
        }

    return {
        "version": "pilot_events_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_policy": [
            "high coverage: highest gold_evidence_in_prompt_ratio",
            "low coverage: lowest gold_evidence_in_prompt_ratio",
            "tuple many: highest gold_tuple_count",
            "chain many: highest chain count in full chain adjudication sheet",
            "model poor: lowest event-level model probe Tuple-F1-soft, prioritizing zero_pred_count",
        ],
        "inputs": {
            "evidence_coverage_by_event": str(coverage_path),
            "gold_quality_by_event": str(gold_quality_path),
            "model_capability_probe_results": str(model_probe_path),
            "chain_adjudication_sheet": str(chain_sheet_path),
        },
        "events": selected,
    }


def add_ranked(
    selected: list[dict[str, Any]],
    used: set[str],
    category: str,
    rows: list[dict[str, Any]],
    reason_builder,
) -> None:
    for row in rows:
        event_id = str(row.get("event_id") or "")
        if event_id and event_id not in used:
            used.add(event_id)
            selected.append({"event_id": event_id, "category": category, "reason": reason_builder(row)})
            return
    raise ValueError(f"no available event for category {category}")


def probe_metric(rows: list[dict[str, str]], event_id: str, field: str) -> float | None:
    for row in rows:
        if row.get("event_id") == event_id:
            return as_float(row.get(field))
    return None


def probe_text(rows: list[dict[str, str]], event_id: str, field: str) -> str:
    for row in rows:
        if row.get("event_id") == event_id:
            return row.get(field, "")
    return ""


def as_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def as_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_json(path: Path, value: dict[str, Any]) -> None:
    backup_existing(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    backup_existing(path)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def backup_existing(path: Path) -> None:
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_{timestamp}"))


def render_report(selection: dict[str, Any]) -> str:
    lines = [
        "# Pilot Event Selection Report",
        "",
        f"- version: {selection['version']}",
        f"- created_at: {selection['created_at']}",
        "",
        "## Selected Events",
        "",
        "| category | event_id | reason | gold_prompt_coverage | tuples | chains | probe_f1 | probe_error |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in selection["events"]:
        metrics = row["metrics"]
        f1 = metrics["model_probe_tuple_f1_soft"]
        f1_text = "" if f1 is None else f"{f1:.4f}"
        lines.append(
            f"| {row['category']} | {row['event_id']} | {row['reason']} | "
            f"{metrics['gold_evidence_in_prompt_ratio']:.4f} | {metrics['gold_tuple_count']} | "
            f"{metrics['chain_count']} | {f1_text} | {metrics['model_probe_error_category']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
