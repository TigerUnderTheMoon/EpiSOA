"""Recompute collection coverage and debug artifacts from existing raw posts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from episoa.collector.coverage_extractor import coverage_debug_rows, evaluate_event_coverage
from episoa.data.loader import read_jsonl, write_jsonl


DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_RAW = Path("outputs/runs/collector_full/raw_posts.jsonl")
DEFAULT_OUTPUT = Path("outputs/runs/collector_full/coverage.json")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    events = read_jsonl(args.events)
    raw_rows = read_jsonl(args.raw)
    output_path = Path(args.output)
    existing_provider_errors = _read_existing_provider_errors(output_path)
    events_by_id = {str(event.get("event_id")): event for event in events}
    raw_by_event: dict[str, list[dict[str, Any]]] = {event_id: [] for event_id in events_by_id}
    for row in raw_rows:
        raw_by_event.setdefault(str(row.get("event_id")), []).append(row)
    coverage_events = {
        event_id: evaluate_event_coverage(event, raw_by_event.get(event_id, []))
        for event_id, event in events_by_id.items()
    }
    missing_events = [event_id for event_id in events_by_id if not raw_by_event.get(event_id)]
    low_coverage_events = []
    for event_id in events_by_id:
        posts = raw_by_event.get(event_id, [])
        coverage = coverage_events[event_id]
        reasons = []
        if len(posts) < int(args.min_raw_per_event):
            reasons.append("raw count below minimum")
        if coverage.get("need_query_repair"):
            reasons.append("coverage needs query repair")
        if reasons:
            low_coverage_events.append({"event_id": event_id, "raw_count": len(posts), "reason": "; ".join(reasons)})
    events_need_recollection = list(low_coverage_events)
    if missing_events or low_coverage_events or events_need_recollection:
        status = "failed"
    elif existing_provider_errors:
        status = "passed_with_provider_warnings"
    else:
        status = "passed"
    report = {
        "status": status,
        "num_events": len(events),
        "num_raw_posts": len(raw_rows),
        "events": coverage_events,
        "errors": existing_provider_errors,
        "provider_errors": existing_provider_errors,
        "missing_events": missing_events,
        "low_coverage_events": low_coverage_events,
        "events_need_recollection": events_need_recollection,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_debug_artifacts(output_path.parent, coverage_events)
    print(f"recomputed coverage for {len(events)} events into {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recompute rule-based collection coverage from raw posts.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--raw", default=str(DEFAULT_RAW))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-raw-per-event", type=int, default=15)
    return parser


def _read_existing_provider_errors(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    errors = payload.get("provider_errors", payload.get("errors", []))
    return list(errors) if isinstance(errors, list) else []


def write_debug_artifacts(output_dir: Path, coverage_by_event: dict[str, dict[str, Any]]) -> None:
    source_rows: list[dict[str, Any]] = []
    stakeholder_rows: list[dict[str, Any]] = []
    stance_rows: list[dict[str, Any]] = []
    temporal_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for event_id, coverage in coverage_by_event.items():
        source_rows.extend({"event_id": event_id, **row} for row in coverage.get("source_detection", []))
        stakeholder_rows.extend({"event_id": event_id, **row} for row in coverage.get("stakeholder_evidence", []))
        stance_rows.extend({"event_id": event_id, **row} for row in coverage.get("stance_evidence", []))
        temporal_rows.extend({"event_id": event_id, **row} for row in coverage.get("temporal_stage_evidence", []))
        coverage_rows.extend(coverage_debug_rows(event_id, coverage))
    write_jsonl(output_dir / "source_detection_debug.jsonl", source_rows)
    write_jsonl(output_dir / "coverage_extraction_debug.jsonl", coverage_rows)
    write_csv(output_dir / "stakeholder_evidence.csv", ["event_id", "stakeholder_type", "raw_id", "matched_text", "matched_rule", "source_type", "confidence", "rule_strength"], stakeholder_rows)
    write_csv(output_dir / "stance_evidence.csv", ["event_id", "stance_type", "raw_id", "matched_text", "matched_rule", "source_type", "confidence", "rule_strength"], stance_rows)
    write_csv(output_dir / "temporal_stage_evidence.csv", ["event_id", "stage_type", "raw_id", "matched_text", "matched_rule", "source_type", "confidence", "rule_strength"], temporal_rows)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
