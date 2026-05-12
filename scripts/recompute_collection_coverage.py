"""Recompute collection coverage and debug artifacts from existing raw posts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
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
    existing_query_plans = _read_existing_query_plans(args)
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

    duplicate_raw_ids = _count_duplicate_raw_ids(raw_rows)
    duplicate_event_url_pairs = _count_event_url_pairs(raw_rows)
    official_missing_events = _find_official_missing_events(events_by_id, coverage_events)
    interaction_missing_events = _find_interaction_missing_events(events_by_id, coverage_events)
    duplicate_query_plan_event_ids = _count_duplicate_plan_event_ids(existing_query_plans)

    low_raw_events = {
        event_id: len(posts)
        for event_id, posts in raw_by_event.items()
        if (count := len(posts)) < int(args.min_raw_per_event)
    }

    data_gate_failed = bool(
        missing_events
        or low_raw_events
        or events_need_recollection
        or duplicate_raw_ids
        or duplicate_event_url_pairs
        or duplicate_query_plan_event_ids
        or official_missing_events
        or interaction_missing_events
    )

    if data_gate_failed:
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
        "provider_warnings": existing_provider_errors if not data_gate_failed else [],
        "missing_events": missing_events,
        "low_coverage_events": low_coverage_events,
        "events_need_recollection": events_need_recollection,
        "duplicate_raw_id_count": len(duplicate_raw_ids),
        "duplicate_raw_ids": duplicate_raw_ids,
        "duplicate_event_url_pair_count": len(duplicate_event_url_pairs),
        "duplicate_event_url_pairs": duplicate_event_url_pairs,
        "duplicate_query_plan_event_id_count": len(duplicate_query_plan_event_ids),
        "duplicate_query_plan_event_ids": duplicate_query_plan_event_ids,
        "official_missing_events": official_missing_events,
        "interaction_missing_events": interaction_missing_events,
        "low_raw_events": low_raw_events,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_debug_artifacts(output_path.parent, coverage_events)
    print(f"recomputed coverage for {len(events)} events into {output_path}")
    return 0


DEFAULT_QUERY_PLAN = Path("data/pubevent_soa_lite/interim/query_plan.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recompute rule-based collection coverage from raw posts.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--raw", default=str(DEFAULT_RAW))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--query-plan", default=str(DEFAULT_QUERY_PLAN))
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


def _read_existing_query_plans(args: argparse.Namespace) -> list[dict[str, Any]]:
    path = Path(getattr(args, "query_plan", str(DEFAULT_QUERY_PLAN)))
    if not path.exists():
        return []
    try:
        return read_jsonl(path)
    except (FileNotFoundError, ValueError):
        return []


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


def _count_duplicate_raw_ids(raw_rows: list[dict[str, Any]]) -> dict[str, int]:
    raw_ids = [str(row.get("raw_id", "")).strip() for row in raw_rows if str(row.get("raw_id", "")).strip()]
    return {raw_id: count for raw_id, count in Counter(raw_ids).items() if count > 1}


def _count_event_url_pairs(raw_rows: list[dict[str, Any]]) -> dict[str, int]:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    def _normalize(url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return ""
        try:
            parts = urlsplit(text)
        except ValueError:
            return text.split("#", 1)[0].strip()
        filtered_query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            lowered = key.lower()
            if lowered.startswith("utm_") or lowered in {"spm", "from", "pvid", "share_from", "scene"}:
                continue
            filtered_query.append((key, value))
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "", urlencode(filtered_query, doseq=True), ""))

    pairs = [
        f"{str(row.get('event_id') or '').strip()}|{_normalize(str(row.get('url') or ''))}"
        for row in raw_rows
        if str(row.get("event_id") or "").strip() and _normalize(str(row.get("url") or ""))
    ]
    return {pair: count for pair, count in Counter(pairs).items() if count > 1}


def _find_official_missing_events(
    events_by_id: dict[str, dict[str, Any]],
    coverage_events: dict[str, dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for event_id, event in events_by_id.items():
        expected_sources = _normalize_source_scope(event.get("source_scope"))
        if "official" not in expected_sources:
            continue
        coverage = coverage_events.get(event_id, {})
        source_counts = coverage.get("source_counts", {})
        if source_counts.get("official", 0) == 0:
            missing.append(event_id)
    return missing


def _find_interaction_missing_events(
    events_by_id: dict[str, dict[str, Any]],
    coverage_events: dict[str, dict[str, Any]],
) -> list[str]:
    interaction_sources = {"public_interaction", "forum", "public_social"}
    missing: list[str] = []
    for event_id, event in events_by_id.items():
        expected_sources = _normalize_source_scope(event.get("source_scope"))
        relevant = expected_sources & interaction_sources
        if not relevant:
            continue
        coverage = coverage_events.get(event_id, {})
        source_counts = coverage.get("source_counts", {})
        if all(source_counts.get(source, 0) == 0 for source in relevant):
            missing.append(event_id)
    return missing


def _normalize_source_scope(value: Any, default_sources: list[str] | None = None) -> set[str]:
    if value is None:
        return set(default_sources or [])
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value).strip()
    if not text:
        return set(default_sources or [])
    return {item.strip() for item in text.split(",") if item.strip()}


def _count_duplicate_plan_event_ids(query_plans: list[dict[str, Any]]) -> dict[str, int]:
    event_ids = [str(plan.get("event_id", "")).strip() for plan in query_plans if str(plan.get("event_id", "")).strip()]
    return {event_id: count for event_id, count in Counter(event_ids).items() if count > 1}


if __name__ == "__main__":
    raise SystemExit(main())
