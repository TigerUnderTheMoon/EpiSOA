"""Run post-collection QC before normalizing raw evidence posts."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl


DEFAULT_RUN_DIR = Path("outputs/runs/collector_full")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
FAIL_FIELDS = ("event_id", "raw_id", "source", "text")
WARN_FIELDS = ("url", "title")
INTERACTION_SOURCES = {"public_interaction", "forum", "public_social"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_qc(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate collected raw posts before normalize/filter.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--raw", default=str(DEFAULT_RUN_DIR / "raw_posts.jsonl"))
    parser.add_argument("--query-plan", default=str(DEFAULT_RUN_DIR / "query_plan.jsonl"))
    parser.add_argument("--coverage", default=str(DEFAULT_RUN_DIR / "coverage.json"))
    parser.add_argument("--output-dir", default=str(DEFAULT_RUN_DIR / "post_collect_qc"))
    parser.add_argument("--min-raw-per-event", type=int, default=15)
    return parser


def run_qc(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    warnings: list[str] = []
    events = _read_jsonl_or_fail(Path(args.events), "events", failures)
    raw_rows = _read_jsonl_or_fail(Path(args.raw), "raw", failures)
    query_plans = _read_jsonl_or_fail(Path(args.query_plan), "query_plan", failures)
    coverage = _read_coverage(Path(args.coverage), failures)

    event_ids = [str(event.get("event_id", "")).strip() for event in events if str(event.get("event_id", "")).strip()]
    expected_event_ids = set(event_ids)
    raw_by_event = _group_by_event(raw_rows)
    source_by_event = _source_counts_by_event(raw_rows)
    coverage_events = coverage.get("events") if isinstance(coverage.get("events"), dict) else {}
    coverage_event_ids = {str(event_id) for event_id in coverage_events}

    null_rows, null_fail_counts, null_warn_counts, required_null_by_event = _null_field_rows(raw_rows)
    for field, count in null_fail_counts.items():
        if count:
            failures.append(f"raw rows missing required field {field}: {count}")
    for field, count in null_warn_counts.items():
        if count:
            warnings.append(f"raw rows missing optional field {field}: {count}")

    duplicate_raw_ids = _duplicates(str(row.get("raw_id", "")).strip() for row in raw_rows if str(row.get("raw_id", "")).strip())
    duplicate_raw_rows = _duplicates(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in raw_rows)
    plan_event_ids = [str(plan.get("event_id", "")).strip() for plan in query_plans]
    duplicate_plan_event_ids = _duplicates(event_id for event_id in plan_event_ids if event_id)

    if duplicate_raw_ids:
        failures.append(f"duplicate raw_id values: {len(duplicate_raw_ids)}")
    if duplicate_raw_rows:
        failures.append(f"duplicate raw rows: {sum(count - 1 for count in duplicate_raw_rows.values())}")
    if duplicate_plan_event_ids:
        failures.append(f"duplicate query plan event_id values: {len(duplicate_plan_event_ids)}")

    if len(query_plans) != len(event_ids):
        failures.append(f"query_plan_rows={len(query_plans)} does not match expected_events={len(event_ids)}")
    if set(plan_event_ids) != expected_event_ids:
        failures.append("query plan event_id set does not match events")
    if coverage.get("num_events") != len(event_ids):
        failures.append(f"coverage_num_events={coverage.get('num_events')} does not match expected_events={len(event_ids)}")
    if coverage_event_ids != expected_event_ids:
        failures.append("coverage event_id set does not match events")
    if set(raw_by_event) != expected_event_ids:
        missing_raw = sorted(expected_event_ids - set(raw_by_event))
        extra_raw = sorted(set(raw_by_event) - expected_event_ids)
        if missing_raw:
            failures.append(f"events missing raw posts: {len(missing_raw)}")
        if extra_raw:
            failures.append(f"raw posts reference unknown events: {len(extra_raw)}")

    raw_count_rows = _raw_count_rows(event_ids, raw_by_event)
    source_distribution_rows = _source_distribution_rows(raw_rows, event_ids, source_by_event)
    low_coverage_events = _low_coverage_rows(
        event_ids=event_ids,
        raw_by_event=raw_by_event,
        source_by_event=source_by_event,
        coverage_events=coverage_events,
        min_raw_per_event=int(args.min_raw_per_event),
        required_null_by_event=required_null_by_event,
    )
    events_need_recollection = [row for row in low_coverage_events if row["need_recollection"]]

    if events_need_recollection:
        failures.append(f"events need recollection: {len(events_need_recollection)}")

    report = {
        "status": "failed" if failures else "passed",
        "num_events_expected": len(event_ids),
        "raw_rows": len(raw_rows),
        "events_with_raw": len(raw_by_event),
        "query_plan_rows": len(query_plans),
        "coverage_num_events": coverage.get("num_events"),
        "failures": failures,
        "warnings": warnings,
        "low_coverage_events": low_coverage_events,
        "events_need_recollection": events_need_recollection,
        "duplicate_raw_ids": duplicate_raw_ids,
        "duplicate_raw_rows": duplicate_raw_rows,
        "duplicate_query_plan_event_ids": duplicate_plan_event_ids,
    }

    _write_json(output_dir / "post_collect_qc_report.json", report)
    _write_csv(output_dir / "raw_count_by_event.csv", ["event_id", "raw_count"], raw_count_rows)
    _write_csv(output_dir / "source_distribution.csv", ["scope", "event_id", "source", "count"], source_distribution_rows)
    _write_csv(output_dir / "null_field_report.csv", ["row_number", "event_id", "raw_id", "field", "severity"], null_rows)
    _write_csv(
        output_dir / "low_coverage_events.csv",
        ["event_id", "raw_count", "need_recollection", "reason", "missing_sources", "coverage_need_query_repair"],
        low_coverage_events,
    )

    print(f"post-collection QC {report['status']}: {output_dir / 'post_collect_qc_report.json'}")
    print(f"raw_rows={len(raw_rows)} events_with_raw={len(raw_by_event)} query_plan_rows={len(query_plans)}")
    if events_need_recollection:
        print(f"events_need_recollection={len(events_need_recollection)}")
    return 0 if report["status"] == "passed" else 1


def _read_jsonl_or_fail(path: Path, label: str, failures: list[str]) -> list[dict[str, Any]]:
    try:
        return read_jsonl(path)
    except (FileNotFoundError, ValueError) as exc:
        failures.append(f"{label} read failed: {exc}")
        return []


def _read_coverage(path: Path, failures: list[str]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            coverage = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        failures.append(f"coverage read failed: {exc}")
        return {}
    if not isinstance(coverage, dict):
        failures.append(f"{path} must contain a JSON object")
        return {}
    return coverage


def _group_by_event(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        event_id = str(row.get("event_id", "")).strip()
        if event_id:
            grouped[event_id].append(row)
    return dict(grouped)


def _source_counts_by_event(rows: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        event_id = str(row.get("event_id", "")).strip()
        source = str(row.get("source") or "unknown").strip() or "unknown"
        if event_id:
            counts[event_id][source] += 1
    return dict(counts)


def _null_field_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str], Counter[str], Counter[str]]:
    report_rows: list[dict[str, Any]] = []
    fail_counts: Counter[str] = Counter()
    warn_counts: Counter[str] = Counter()
    required_null_by_event: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        for field in FAIL_FIELDS:
            if not str(row.get(field) or "").strip():
                fail_counts[field] += 1
                event_id = str(row.get("event_id") or "unknown").strip() or "unknown"
                required_null_by_event[event_id] += 1
                report_rows.append(_null_field_row(index, row, field, "fail"))
        for field in WARN_FIELDS:
            if not str(row.get(field) or "").strip():
                warn_counts[field] += 1
                report_rows.append(_null_field_row(index, row, field, "warn"))
    return report_rows, fail_counts, warn_counts, required_null_by_event


def _null_field_row(index: int, row: dict[str, Any], field: str, severity: str) -> dict[str, Any]:
    return {
        "row_number": index,
        "event_id": row.get("event_id", ""),
        "raw_id": row.get("raw_id", ""),
        "field": field,
        "severity": severity,
    }


def _duplicates(values: Any) -> dict[str, int]:
    counts = Counter(values)
    return {value: count for value, count in counts.items() if count > 1}


def _raw_count_rows(event_ids: list[str], raw_by_event: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"event_id": event_id, "raw_count": len(raw_by_event.get(event_id, []))} for event_id in event_ids]


def _source_distribution_rows(
    raw_rows: list[dict[str, Any]],
    event_ids: list[str],
    source_by_event: dict[str, Counter[str]],
) -> list[dict[str, Any]]:
    rows = [
        {"scope": "all", "event_id": "", "source": source, "count": count}
        for source, count in Counter(str(row.get("source") or "unknown") for row in raw_rows).most_common()
    ]
    for event_id in event_ids:
        for source, count in source_by_event.get(event_id, Counter()).most_common():
            rows.append({"scope": "event", "event_id": event_id, "source": source, "count": count})
    return rows


def _low_coverage_rows(
    *,
    event_ids: list[str],
    raw_by_event: dict[str, list[dict[str, Any]]],
    source_by_event: dict[str, Counter[str]],
    coverage_events: dict[str, Any],
    min_raw_per_event: int,
    required_null_by_event: Counter[str],
) -> list[dict[str, Any]]:
    rows = []
    for event_id in event_ids:
        raw_count = len(raw_by_event.get(event_id, []))
        source_counts = source_by_event.get(event_id, Counter())
        coverage = coverage_events.get(event_id, {})
        coverage_repair = bool(isinstance(coverage, dict) and coverage.get("need_query_repair"))
        missing = _missing_sources(source_counts)
        reasons = []
        if raw_count == 0:
            reasons.append("no raw posts")
        if raw_count < min_raw_per_event:
            reasons.append("raw count below minimum")
        if "official" in missing:
            reasons.append("official evidence missing")
        if all(source in missing for source in INTERACTION_SOURCES):
            reasons.append("public_interaction/forum/public_social evidence missing")
        if coverage_repair:
            reasons.append("coverage needs query repair")
        if required_null_by_event.get(event_id, 0):
            reasons.append("required raw field missing")
        reasons.extend(_coverage_missing_reasons(coverage))
        if reasons:
            rows.append(
                {
                    "event_id": event_id,
                    "raw_count": raw_count,
                    "need_recollection": True,
                    "reason": "; ".join(dict.fromkeys(reasons)),
                    "missing_sources": ",".join(missing),
                    "coverage_need_query_repair": coverage_repair,
                }
            )
    return rows


def _missing_sources(source_counts: Counter[str]) -> list[str]:
    missing = []
    if source_counts.get("official", 0) == 0:
        missing.append("official")
    for source in sorted(INTERACTION_SOURCES):
        if source_counts.get(source, 0) == 0:
            missing.append(source)
    return missing


def _coverage_missing_reasons(coverage: Any) -> list[str]:
    if not isinstance(coverage, dict):
        return ["coverage event missing"]
    fields = (
        ("missing_sources", "coverage missing sources"),
        ("missing_stakeholders", "coverage missing stakeholders"),
        ("missing_stances", "coverage missing stances"),
        ("missing_temporal_stages", "coverage missing temporal stages"),
    )
    return [reason for field, reason in fields if coverage.get(field)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
