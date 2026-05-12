"""Run C-FSM evidence collection and write raw posts."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from episoa.collector.query_planner import (
    DEFAULT_SOURCES,
    DEFAULT_TEMPORAL_STAGES,
    SOURCE_ALIASES,
    as_list as _planner_as_list,
    build_repair_rounds as _planner_build_repair_rounds,
    dedupe_rounds as _planner_dedupe_rounds,
    evaluate_coverage as _planner_evaluate_coverage,
    normalize_source_scope as _planner_normalize_source_scope,
    normalize_source_type as _planner_normalize_source_type,
    plan_event_queries as _planner_plan_event_queries,
    plan_recollection_queries as _planner_plan_recollection_queries,
    unique as _planner_unique,
)
from episoa.collector.coverage_extractor import coverage_debug_rows, enrich_record_source
from episoa.collector.coverage_extractor import classify_source, extract_domain
from episoa.collector.search_client import SearchClient, load_search_config
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.data.validator import validate_formal_event_record


DEFAULT_EVENTS_PATH = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_CONFIG_PATH = Path("configs/collector.yaml")
DEFAULT_RAW_POSTS_PATH = Path("data/pubevent_soa_lite/raw/raw_posts.jsonl")
DEFAULT_INTERIM_DIR = Path("data/pubevent_soa_lite/interim")
DEFAULT_QUERY_PLAN_PATH = DEFAULT_INTERIM_DIR / "query_plan.jsonl"
DEFAULT_COVERAGE_REPORT_PATH = DEFAULT_INTERIM_DIR / "coverage.json"
DEFAULT_RECOLLECTION_DEBUG_PATH = DEFAULT_INTERIM_DIR / "recollection_debug_report.json"
DEFAULT_QUERY_PLANNER_DEBUG_PATH = DEFAULT_INTERIM_DIR / "query_planner_debug.json"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return collect_from_cli(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect raw evidence posts through the C-FSM stage.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--output", default=str(DEFAULT_RAW_POSTS_PATH))
    parser.add_argument("--query-plan-output", default=str(DEFAULT_QUERY_PLAN_PATH))
    parser.add_argument("--coverage-output", default=str(DEFAULT_COVERAGE_REPORT_PATH))
    parser.add_argument("--planner-debug-output", default=str(DEFAULT_QUERY_PLANNER_DEBUG_PATH))
    parser.add_argument("--recollection", action="store_true", help="Read recollection_plan.jsonl rows instead of full event configs.")
    parser.add_argument("--resume", action="store_true", help="Continue an interrupted collection without repeating completed events.")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-queries-per-event", type=int, default=6)
    parser.add_argument("--debug-output", default=str(DEFAULT_RECOLLECTION_DEBUG_PATH))
    return parser


def build_initial_query_plans(
    *,
    events: list[dict[str, Any]],
    planner_mode: str,
    default_sources: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plans = [plan_event_queries(event, default_sources=default_sources) for event in events]
    fallback_reason = None if planner_mode == "heuristic" else "unsupported_planner_mode"
    notes = [] if fallback_reason is None else ["unsupported planner mode requested; used heuristic planner"]
    return plans, _planner_debug_payload(
        requested_mode=planner_mode,
        effective_mode="heuristic",
        fallback_reason=fallback_reason,
        status="completed",
        num_events=len(events),
        events=[
            {
                "event_id": event.get("event_id"),
                "planner_mode": "heuristic",
                "requested_mode": planner_mode,
                "effective_mode": "heuristic",
                "fallback_reason": fallback_reason,
                "selected_queries": [item["query"] for item in plan["query_rounds"]],
                "temporal_stage_coverage_mode": "literal_string_match_legacy",
                "notes": notes,
            }
            for event, plan in zip(events, plans, strict=True)
        ],
    )


def _planner_debug_payload(
    *,
    requested_mode: str,
    effective_mode: str | None,
    fallback_reason: str | None,
    status: str,
    num_events: int,
    events: list[dict[str, Any]],
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "blocked_reason": blocked_reason,
        "num_events": num_events,
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "planner_mode": effective_mode or "not_run",
        "events": events,
    }


def collect_from_cli(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    config_path = Path(args.config)
    output_path = Path(args.output)
    query_plan_path = Path(args.query_plan_output)
    coverage_path = Path(args.coverage_output)
    debug_path = Path(args.debug_output)
    planner_debug_path = Path(getattr(args, "planner_debug_output", DEFAULT_QUERY_PLANNER_DEBUG_PATH))
    if args.recollection and args.query_plan_output == str(DEFAULT_QUERY_PLAN_PATH):
        query_plan_path = DEFAULT_INTERIM_DIR / "recollection_query_plan.jsonl"
    if args.recollection and args.coverage_output == str(DEFAULT_COVERAGE_REPORT_PATH):
        coverage_path = DEFAULT_INTERIM_DIR / "recollection_coverage_report.json"

    config = _load_yaml(config_path)
    search_config = load_search_config(dict(config.get("search", {})))
    collector_config = dict(config.get("collector", {}))
    default_sources = normalize_source_scope(collector_config.get("source_types") or DEFAULT_SOURCES)
    force_source_types = bool(collector_config.get("force_source_types", False))
    max_results_per_query = int(collector_config.get("max_results_per_query", 10))
    max_evidence_per_event = int(collector_config.get("max_evidence_per_event", 50))
    min_raw_per_event = int(collector_config.get("min_raw_per_event", 15))
    max_queries_per_event = int(collector_config.get("max_queries_per_event", args.max_queries_per_event))
    max_repair_rounds = int(collector_config.get("max_repair_rounds", 2))
    sleep_seconds = float(collector_config.get("sleep_seconds", 0.5))
    planner_config = dict(collector_config.get("query_planner") or {})
    requested_planner_mode = str(planner_config.get("mode", "heuristic")).strip().lower() or "heuristic"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    query_plan_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    planner_debug_path.parent.mkdir(parents=True, exist_ok=True)
    resume = bool(getattr(args, "resume", False))
    if args.recollection and resume:
        print("WARNING: --resume is only supported for initial collection, not recollection.")
        return 1

    if args.recollection:
        output_path.write_text("", encoding="utf-8")

    try:
        events = read_jsonl(events_path)
        if args.max_events is not None:
            events = events[: args.max_events]
    except (FileNotFoundError, ValueError) as exc:
        write_jsonl(query_plan_path, [])
        write_jsonl(output_path, [])
        _write_json(
            planner_debug_path,
            _planner_debug_payload(
                requested_mode=requested_planner_mode,
                effective_mode=None,
                fallback_reason="events_read_failed",
                status="blocked",
                blocked_reason=str(exc),
                num_events=0,
                events=[],
            ),
        )
        _write_json(
            coverage_path,
            {
                "status": "blocked",
                "collection_skipped_reason": str(exc),
                "events_path": str(events_path),
            },
        )
        print(f"WARNING: {exc}")
        return 1

    if not events:
        write_jsonl(query_plan_path, [])
        empty_requested_mode = "recollection" if args.recollection else requested_planner_mode
        _write_json(
            planner_debug_path,
            _planner_debug_payload(
                requested_mode=empty_requested_mode,
                effective_mode=None,
                fallback_reason="no_events",
                status="blocked",
                blocked_reason="no accepted formal events found; populate events.jsonl before evidence collection",
                num_events=0,
                events=[],
            ),
        )
        if not output_path.exists():
            write_jsonl(output_path, [])
        if args.recollection:
            write_debug_report(debug_path, init_debug_report(0), output_path)
        _write_json(
            coverage_path,
            {
                "status": "blocked",
                "collection_skipped_reason": "no accepted formal events found; populate events.jsonl before evidence collection",
                "planned_only": True,
                "num_events": 0,
            },
        )
        print("WARNING: no accepted formal events found; populate events.jsonl before evidence collection.")
        return 0

    if not args.recollection:
        formal_errors = [
            error
            for index, event in enumerate(events, start=1)
            for error in validate_formal_event_record(event, f"events:{index}")
        ]
        if formal_errors:
            if not output_path.exists():
                write_jsonl(output_path, [])
            _write_json(
                planner_debug_path,
                _planner_debug_payload(
                    requested_mode=requested_planner_mode,
                    effective_mode=None,
                    fallback_reason="formal_validation_failed",
                    status="blocked",
                    blocked_reason="events.jsonl contains non-formal event records",
                    num_events=len(events),
                    events=[],
                ),
            )
            _write_json(
                coverage_path,
                {
                    "status": "blocked",
                    "collection_skipped_reason": (
                        "events.jsonl must contain accepted concrete formal event instances before evidence collection"
                    ),
                    "errors": formal_errors,
                    "planned_only": True,
                    "num_events": len(events),
                },
            )
            print("WARNING: events.jsonl contains non-formal event records; no raw posts were collected.")
            return 1

    if force_source_types:
        events = [_with_forced_source_scope(event, default_sources) for event in events]

    if args.recollection:
        query_plans = [plan_recollection_queries(event, default_sources=default_sources) for event in events]
        _write_json(
            planner_debug_path,
            _planner_debug_payload(
                requested_mode="recollection",
                effective_mode="recollection",
                fallback_reason=None,
                status="completed",
                num_events=len(events),
                events=[],
            ),
        )
    else:
        query_plans, planner_debug = build_initial_query_plans(
            events=events,
            planner_mode=requested_planner_mode,
            default_sources=default_sources,
        )
        if resume:
            query_plans = _merge_existing_query_plans(query_plan_path, query_plans)
        _write_json(planner_debug_path, planner_debug)
    write_jsonl(query_plan_path, query_plans)

    if not search_config.configured:
        for plan in query_plans:
            plan["planned_only"] = True
        write_jsonl(query_plan_path, query_plans)
        write_jsonl(output_path, [])
        if args.recollection:
            debug = init_debug_report(len(events))
            debug["queries_generated"] = sum(min(len(plan["query_rounds"]), max_queries_per_event) for plan in query_plans)
            write_debug_report(debug_path, debug, output_path)
        _write_json(
            coverage_path,
            {
                "status": "blocked",
                "planned_only": True,
                "collection_skipped_reason": (
                    "search.api_key or search.base_url is missing. Fill configs/collector.yaml "
                    "or set SEARCH_API_KEY/SEARCH_BASE_URL."
                ),
                "api_key_source": search_config.api_key_source,
                "base_url_source": search_config.base_url_source,
                "num_events": len(events),
            },
        )
        print("WARNING: search API is not configured; wrote query_plan.jsonl only.")
        return 0

    client = SearchClient(search_config)
    if args.recollection:
        debug = init_debug_report(len(events))
        debug["queries_generated"] = sum(min(len(plan["query_rounds"]), max_queries_per_event) for plan in query_plans)
        per_event_posts, errors = collect_recollection_streaming(
            client=client,
            events=events,
            query_plans=query_plans,
            output_path=output_path,
            max_results_per_query=max_results_per_query,
            max_evidence_per_event=max_evidence_per_event,
            sleep_seconds=sleep_seconds,
            max_queries_per_event=max_queries_per_event,
            debug=debug,
            debug_path=debug_path,
        )
        write_jsonl(query_plan_path, query_plans)
        report = build_coverage_report(
            events,
            per_event_posts,
            errors,
            default_sources=default_sources,
            min_raw_per_event=min_raw_per_event,
        )
        _write_json(coverage_path, report)
        write_debug_report(debug_path, debug, output_path)
        print(f"Collected {debug['raw_posts_collected']} recollection raw posts into {output_path}")
        return 0

    all_posts: list[dict[str, Any]] = []
    per_event_posts: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []
    first_pass_by_event: dict[str, dict[str, Any]] = {}
    second_pass_by_event: dict[str, dict[str, Any]] = {}
    repair_queries: list[dict[str, Any]] = []
    repair_collection_summary: dict[str, Any] = {"events": {}, "attempts": []}
    official_repair_queries: list[dict[str, Any]] = []
    stance_repair_queries: list[dict[str, Any]] = []
    temporal_repair_queries: list[dict[str, Any]] = []
    low_raw_repair_queries: list[dict[str, Any]] = []
    completed_event_ids: set[str] = set()
    if resume:
        existing_posts = _read_existing_jsonl(output_path)
        per_event_posts.update(_group_posts_by_event(existing_posts))
        completed_event_ids = set(per_event_posts)
        completed_event_ids.update(_read_completed_event_ids(coverage_path))
        completed_event_ids.intersection_update(str(event.get("event_id", "")) for event in events)
        completed_event_ids = {event_id for event_id in completed_event_ids if event_id}
        all_posts.extend(existing_posts)
        repair_collection_summary = _read_existing_repair_collection_summary(
            query_plan_path.parent / "repair_collection_summary.json"
        )
        repair_queries = _read_existing_jsonl(query_plan_path.parent / "repair_queries.jsonl")
        official_repair_queries = _read_existing_jsonl(query_plan_path.parent / "official_repair_queries.jsonl")
        stance_repair_queries = _read_existing_jsonl(query_plan_path.parent / "stance_repair_queries.jsonl")
        temporal_repair_queries = _read_existing_jsonl(query_plan_path.parent / "temporal_repair_queries.jsonl")
        low_raw_repair_queries = _read_existing_jsonl(query_plan_path.parent / "low_raw_repair_queries.jsonl")
        errors = _read_existing_coverage_errors(coverage_path)
        print(f"[resume] completed_events={len(completed_event_ids)}", flush=True)
    else:
        output_path.write_text("", encoding="utf-8")

    for event_index, (event, plan) in enumerate(zip(events, query_plans, strict=True), start=1):
        event_id = str(event.get("event_id", ""))
        if event_id in completed_event_ids:
            print(f"[event {event_index}/{len(events)}] skip completed event_id={event_id}", flush=True)
            continue
        print(f"[event {event_index}/{len(events)}] start event_id={event_id}", flush=True)
        event_started_at = time.perf_counter()
        first_pass_attempts: list[dict[str, Any]] = []
        first_pass_started_at = time.perf_counter()
        event_posts = _collect_for_plan(
            client,
            event,
            plan,
            max_results_per_query=max_results_per_query,
            max_evidence_per_event=max_evidence_per_event,
            max_queries_per_event=max_queries_per_event,
            sleep_seconds=sleep_seconds,
            errors=errors,
            attempts=first_pass_attempts,
        )
        event_posts = _dedupe_posts(event_posts)
        first_pass_seconds = time.perf_counter() - first_pass_started_at
        coverage = evaluate_coverage(event, event_posts, default_sources=default_sources)
        if len(event_posts) < min_raw_per_event:
            coverage["missing_raw_count"] = max(0, min_raw_per_event - len(event_posts))
            coverage["need_query_repair"] = True
        first_pass_by_event[event_id] = coverage
        repair_round = 1
        event_repair_attempts: list[dict[str, Any]] = []
        event_repair_queries: list[dict[str, Any]] = []
        repair_seconds = 0.0
        before_repair_count = len(event_posts)
        before_missing = _coverage_missing_summary(coverage)
        while coverage["need_query_repair"] and repair_round <= max_repair_rounds:
            repair_rounds = build_repair_rounds(event, coverage, repair_round, default_sources=default_sources)
            event_repair_queries.extend(repair_rounds)
            repair_queries.extend([{"event_id": event_id, **item} for item in repair_rounds])
            stance_repair_queries.extend(
                [{"event_id": event_id, **item} for item in repair_rounds if item.get("reason") == "missing stance"]
            )
            temporal_repair_queries.extend(
                [{"event_id": event_id, **item} for item in repair_rounds if item.get("reason") == "missing temporal stage"]
            )
            low_raw_repair_queries.extend(
                [{"event_id": event_id, **item} for item in repair_rounds if item.get("reason") == "raw count below minimum"]
            )
            official_repair_queries.extend(
                [
                    {"event_id": event_id, **item}
                    for item in repair_rounds
                    if item.get("source_type") == "official" and item.get("reason") == "missing_official"
                ]
            )
            plan["query_rounds"].extend(repair_rounds)
            plan["repair_keywords"].extend([item["query"] for item in repair_rounds])
            repair_started_at = time.perf_counter()
            repair_remaining = max_evidence_per_event - len(event_posts)
            if repair_remaining <= 0 and (
                coverage.get("missing_sources") or coverage.get("missing_stances") or coverage.get("missing_temporal_stages")
            ):
                repair_remaining = max_results_per_query * min(len(repair_rounds), max_queries_per_event)
            if repair_remaining <= 0:
                break
            event_posts.extend(
                _collect_rounds(
                    client,
                    event,
                    repair_rounds[:max_queries_per_event],
                    max_results_per_query=max_results_per_query,
                    remaining=repair_remaining,
                    sleep_seconds=sleep_seconds,
                    errors=errors,
                    attempts=event_repair_attempts,
                )
            )
            repair_seconds += time.perf_counter() - repair_started_at
            event_posts = _dedupe_posts(event_posts)
            coverage = evaluate_coverage(event, event_posts, default_sources=default_sources)
            if len(event_posts) < min_raw_per_event:
                coverage["missing_raw_count"] = max(0, min_raw_per_event - len(event_posts))
                coverage["need_query_repair"] = True
            repair_round += 1
        second_pass_by_event[event_id] = coverage
        after_missing = _coverage_missing_summary(coverage)
        repair_collection_summary["attempts"].extend(event_repair_attempts)
        repair_collection_summary["events"][event_id] = {
            "first_pass_attempts": first_pass_attempts,
            "repair_attempts": event_repair_attempts,
            "repair_queries": len(event_repair_queries),
            "repair_queries_executed": len(event_repair_attempts),
            "raw_posts_before_repair": before_repair_count,
            "raw_posts_after_repair": len(event_posts),
            "event_seconds": round(time.perf_counter() - event_started_at, 4),
            "first_pass_seconds": round(first_pass_seconds, 4),
            "repair_seconds": round(repair_seconds, 4),
            "source_seconds": _source_seconds([*first_pass_attempts, *event_repair_attempts]),
            "missing_before": before_missing,
            "missing_after": after_missing,
        }
        per_event_posts[event_id] = event_posts
        all_posts.extend(event_posts)
        with output_path.open("a", encoding="utf-8") as handle:
            for post in event_posts:
                handle.write(json.dumps(post, ensure_ascii=False) + "\n")
            handle.flush()
        write_jsonl(query_plan_path, query_plans)
        write_jsonl(query_plan_path.parent / "repair_queries.jsonl", repair_queries)
        write_jsonl(query_plan_path.parent / "official_repair_queries.jsonl", official_repair_queries)
        write_jsonl(query_plan_path.parent / "stance_repair_queries.jsonl", stance_repair_queries)
        write_jsonl(query_plan_path.parent / "temporal_repair_queries.jsonl", temporal_repair_queries)
        write_jsonl(query_plan_path.parent / "low_raw_repair_queries.jsonl", low_raw_repair_queries)
        _write_json(query_plan_path.parent / "first_pass_coverage.json", _coverage_snapshot(first_pass_by_event))
        _write_json(query_plan_path.parent / "second_pass_coverage.json", _coverage_snapshot(second_pass_by_event))
        _write_json(query_plan_path.parent / "repair_collection_summary.json", repair_collection_summary)
        _write_low_raw_repair_summary(query_plan_path.parent, low_raw_repair_queries, repair_collection_summary)
        _write_provider_error_summary(query_plan_path.parent, errors, repair_collection_summary)
        _write_provider_attempt_summary(query_plan_path.parent, repair_collection_summary)
        _write_official_repair_artifacts(query_plan_path.parent, official_repair_queries, repair_collection_summary)
        _write_json(
            query_plan_path.parent / "repair_delta_summary.json",
            _repair_delta_summary(first_pass_by_event, second_pass_by_event, per_event_posts),
        )
        _write_coverage_debug_artifacts(query_plan_path.parent, second_pass_by_event)
        report = build_coverage_report(
            events[:event_index],
            per_event_posts,
            errors,
            default_sources=default_sources,
            min_raw_per_event=min_raw_per_event,
            query_plans=query_plans,
        )
        _write_json(coverage_path, report)
        print(f"[event {event_index}/{len(events)}] done event_id={event_id} raw_posts={len(event_posts)}", flush=True)

    write_jsonl(query_plan_path, query_plans)
    write_jsonl(query_plan_path.parent / "official_repair_queries.jsonl", official_repair_queries)
    write_jsonl(query_plan_path.parent / "stance_repair_queries.jsonl", stance_repair_queries)
    write_jsonl(query_plan_path.parent / "temporal_repair_queries.jsonl", temporal_repair_queries)
    write_jsonl(query_plan_path.parent / "low_raw_repair_queries.jsonl", low_raw_repair_queries)
    _write_official_repair_artifacts(query_plan_path.parent, official_repair_queries, repair_collection_summary)
    _write_low_raw_repair_summary(query_plan_path.parent, low_raw_repair_queries, repair_collection_summary)
    _write_provider_error_summary(query_plan_path.parent, errors, repair_collection_summary)
    _write_provider_attempt_summary(query_plan_path.parent, repair_collection_summary)
    report = build_coverage_report(
        events,
        per_event_posts,
        errors,
        default_sources=default_sources,
        min_raw_per_event=min_raw_per_event,
        query_plans=query_plans,
    )
    _write_json(coverage_path, report)
    print(f"Collected {len(all_posts)} raw posts into {output_path}")
    return 0


def plan_event_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    return _planner_plan_event_queries(event, default_sources=default_sources)


def plan_recollection_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    return _planner_plan_recollection_queries(event, default_sources=default_sources)


def _with_forced_source_scope(event: dict[str, Any], source_scope: list[str]) -> dict[str, Any]:
    updated = dict(event)
    updated["source_scope"] = list(source_scope)
    return updated


def evaluate_coverage(
    event: dict[str, Any], posts: list[dict[str, Any]], default_sources: list[str] | None = None
) -> dict[str, Any]:
    return _planner_evaluate_coverage(event, posts, default_sources=default_sources)


def build_repair_rounds(
    event: dict[str, Any], coverage: dict[str, Any], repair_round: int, default_sources: list[str] | None = None
) -> list[dict[str, Any]]:
    return _planner_build_repair_rounds(event, coverage, repair_round, default_sources=default_sources)


def build_coverage_report(
    events: list[dict[str, Any]],
    per_event_posts: dict[str, list[dict[str, Any]]],
    errors: list[dict[str, Any]],
    default_sources: list[str] | None = None,
    min_raw_per_event: int = 15,
    query_plans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    event_reports = {}
    missing_events: list[str] = []
    low_coverage_events: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id", ""))
        posts = per_event_posts.get(event_id, [])
        coverage = evaluate_coverage(event, posts, default_sources=default_sources)
        event_reports[event_id] = coverage
        reasons = []
        if not posts:
            missing_events.append(event_id)
            reasons.append("missing raw posts")
        if len(posts) < min_raw_per_event:
            reasons.append("raw count below minimum")
        if coverage.get("need_query_repair"):
            reasons.append("coverage needs query repair")
        if reasons:
            low_coverage_events.append(
                {
                    "event_id": event_id,
                    "raw_count": len(posts),
                    "reason": "; ".join(dict.fromkeys(reasons)),
                }
            )
    provider_errors = list(errors)
    events_need_recollection = list(low_coverage_events)

    duplicate_raw_ids = _count_event_duplicate_raw_ids(per_event_posts)
    duplicate_event_url_pairs = _count_event_url_pairs(per_event_posts)
    official_missing_events = _find_official_missing_events(events, per_event_posts, event_reports)
    interaction_missing_events = _find_interaction_missing_events(events, per_event_posts, event_reports)
    duplicate_query_plan_event_ids = _count_duplicate_plan_event_ids(query_plans) if query_plans else {}

    low_raw_events = {
        event_id: count
        for event_id, posts in per_event_posts.items()
        if (count := len(posts)) < min_raw_per_event
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
    elif provider_errors:
        status = "passed_with_provider_warnings"
    else:
        status = "passed"

    return {
        "status": status,
        "num_events": len(events),
        "num_raw_posts": sum(len(items) for items in per_event_posts.values()),
        "events": event_reports,
        "errors": provider_errors,
        "provider_errors": provider_errors,
        "provider_warnings": provider_errors if not data_gate_failed else [],
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


def collect_recollection_streaming(
    *,
    client: SearchClient,
    events: list[dict[str, Any]],
    query_plans: list[dict[str, Any]],
    output_path: Path,
    max_results_per_query: int,
    max_evidence_per_event: int,
    sleep_seconds: float,
    max_queries_per_event: int,
    debug: dict[str, Any],
    debug_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    per_event_posts: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []
    total_events = len(events)
    with output_path.open("a", encoding="utf-8") as handle:
        for event_index, (event, plan) in enumerate(zip(events, query_plans, strict=True), start=1):
            event_id = str(event.get("event_id", ""))
            event_posts: list[dict[str, Any]] = []
            seen_event_urls: set[tuple[str, str]] = set()
            rounds = list(plan["query_rounds"])[:max_queries_per_event]
            debug["events_attempted"] += 1
            event_stats = {
                "event_id": event_id,
                "queries_attempted": 0,
                "api_calls_attempted": 0,
                "api_calls_succeeded": 0,
                "api_calls_failed": 0,
                "timeout_count": 0,
                "raw_posts_collected": 0,
            }
            for query_index, item in enumerate(rounds, start=1):
                if len(event_posts) >= max_evidence_per_event:
                    break
                event_stats["queries_attempted"] += 1
                source_scope = normalize_source_scope(item.get("source_scope"))
                for source_type in source_scope:
                    if len(event_posts) >= max_evidence_per_event:
                        break
                    debug["api_calls_attempted"] += 1
                    event_stats["api_calls_attempted"] += 1
                    print(
                        f"[event {event_index}/{total_events}] [query {query_index}/{len(rounds)}] "
                        f"source={source_type} query={item['query']}",
                        flush=True,
                    )
                    response = client.search_with_debug(
                        query=str(item["query"]),
                        max_results=max_results_per_query,
                        source_type=str(source_type),
                        time_window=event.get("time_window"),
                    )
                    results = _rank_results_for_source(list(response["results"]), source_type)
                    if response["ok"]:
                        debug["api_calls_succeeded"] += 1
                        event_stats["api_calls_succeeded"] += 1
                    else:
                        debug["api_calls_failed"] += 1
                        event_stats["api_calls_failed"] += 1
                        if response.get("timeout"):
                            debug["timeout_count"] += 1
                            event_stats["timeout_count"] += 1
                        error = {
                            "event_id": event_id,
                            "query": item["query"],
                            "target_source": source_type,
                            "error_type": response.get("error_type"),
                            "error": response.get("error"),
                        }
                        errors.append(error)
                        debug["per_query_errors"].append(error)
                    written = 0
                    for result in results:
                        text = str(result.get("text") or result.get("snippet") or result.get("title") or "").strip()
                        if not text:
                            continue
                        url = str(result.get("url") or "").strip()
                        event_url = _event_url_key(event_id, url)
                        if event_url and event_url in seen_event_urls:
                            continue
                        if url:
                            seen_event_urls.add(event_url)
                        post = _raw_post(event_id, item, source_type, result, text)
                        handle.write(json.dumps(post, ensure_ascii=False) + "\n")
                        handle.flush()
                        event_posts.append(post)
                        debug["raw_posts_collected"] += 1
                        event_stats["raw_posts_collected"] += 1
                        written += 1
                        if len(event_posts) >= max_evidence_per_event:
                            break
                    print(
                        f"[event {event_index}/{total_events}] [query {query_index}/{len(rounds)}] "
                        f"source={source_type} result_count={len(results)} written={written} "
                        f"error={response.get('error_type') or ''}",
                        flush=True,
                    )
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
            per_event_posts[event_id] = event_posts
            debug["per_event_stats"].append(event_stats)
            write_debug_report(debug_path, debug, output_path)
    return per_event_posts, errors


def init_debug_report(plan_rows_loaded: int) -> dict[str, Any]:
    return {
        "plan_rows_loaded": plan_rows_loaded,
        "events_attempted": 0,
        "queries_generated": 0,
        "api_calls_attempted": 0,
        "api_calls_succeeded": 0,
        "api_calls_failed": 0,
        "timeout_count": 0,
        "raw_posts_collected": 0,
        "per_event_stats": [],
        "per_query_errors": [],
    }


def write_debug_report(path: Path, debug: dict[str, Any], output_path: Path) -> None:
    debug = dict(debug)
    debug["output_path"] = str(output_path)
    _write_json(path, debug)


def _collect_for_plan(
    client: SearchClient,
    event: dict[str, Any],
    plan: dict[str, Any],
    *,
    max_results_per_query: int,
    max_evidence_per_event: int,
    max_queries_per_event: int,
    sleep_seconds: float,
    errors: list[dict[str, Any]],
    attempts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return _collect_rounds(
        client,
        event,
        list(plan["query_rounds"])[:max_queries_per_event],
        max_results_per_query=max_results_per_query,
        remaining=max_evidence_per_event,
        sleep_seconds=sleep_seconds,
        errors=errors,
        attempts=attempts,
    )


def _collect_rounds(
    client: SearchClient,
    event: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    max_results_per_query: int,
    remaining: int,
    sleep_seconds: float,
    errors: list[dict[str, Any]],
    attempts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    event_id = str(event.get("event_id", ""))
    posts: list[dict[str, Any]] = []
    seen_event_urls: set[tuple[str, str]] = set()
    source_counts: Counter[str] = Counter()
    planned_sources = sorted({source for item in rounds for source in _round_sources(item)})
    per_source_limit = max(1, remaining // max(1, len(planned_sources)), remaining // 2)
    for item in rounds:
        for source_type in _round_sources(item):
            if len(posts) >= remaining or source_counts[source_type] >= per_source_limit:
                continue
            response: dict[str, Any]
            if hasattr(client, "search_with_debug"):
                started_at = time.perf_counter()
                response = client.search_with_debug(
                    query=str(item["query"]),
                    max_results=max_results_per_query,
                    source_type=str(source_type),
                    time_window=event.get("time_window"),
                )
                duration_seconds = time.perf_counter() - started_at
                results = _rank_results_for_source(list(response.get("results") or []), source_type)
            else:
                try:
                    started_at = time.perf_counter()
                    results = client.search(
                        query=str(item["query"]),
                        max_results=max_results_per_query,
                        source_type=str(source_type),
                        time_window=event.get("time_window"),
                    )
                    results = _rank_results_for_source(list(results), source_type)
                    duration_seconds = time.perf_counter() - started_at
                    response = {"ok": True, "results": results, "error_type": None, "error": None}
                except RuntimeError as exc:
                    duration_seconds = time.perf_counter() - started_at
                    response = {"ok": False, "results": [], "error_type": type(exc).__name__, "error": str(exc)}
                    results = []
            if not response.get("ok"):
                errors.append(
                    {
                        "event_id": event_id,
                        "query": item["query"],
                        "source_type": source_type,
                        "provider": getattr(getattr(client, "config", None), "provider", "search_client"),
                        "error_type": response.get("error_type"),
                        "error": response.get("error"),
                        "duration_seconds": round(duration_seconds, 4),
                        "retry_count": int(response.get("retry_count") or 0),
                        "final_status": response.get("final_status") or "failed",
                        "provider_attempts": list(response.get("provider_attempts") or []),
                    }
                )
            official_stats = _official_detection_stats(results, source_type)
            written = 0
            for result in results:
                if len(posts) >= remaining or source_counts[source_type] >= per_source_limit:
                    break
                text = str(result.get("text") or result.get("snippet") or result.get("title") or "").strip()
                if not text:
                    continue
                url = str(result.get("url") or "").strip()
                event_url = _event_url_key(event_id, url)
                if event_url and event_url in seen_event_urls:
                    continue
                if url:
                    seen_event_urls.add(event_url)
                posts.append(_raw_post(event_id, item, source_type, result, text))
                source_counts[source_type] += 1
                written += 1
            if attempts is not None:
                attempts.append(
                    {
                        "event_id": event_id,
                        "query": item["query"],
                        "source_type": source_type,
                        "result_count": len(results),
                        "written": written,
                        "ok": bool(response.get("ok")),
                        "error_type": response.get("error_type"),
                        "error": response.get("error"),
                        "duration_seconds": round(duration_seconds, 4),
                        "provider": getattr(getattr(client, "config", None), "provider", "search_client"),
                        "retry_count": int(response.get("retry_count") or 0),
                        "final_status": response.get("final_status") or ("success" if response.get("ok") else "failed"),
                        "provider_attempts": list(response.get("provider_attempts") or []),
                        "empty_source_attempt": len(results) == 0 or written == 0,
                        **official_stats,
                    }
                )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    return posts


def _rank_results_for_source(results: list[dict[str, Any]], source_type: str) -> list[dict[str, Any]]:
    if normalize_source_type(source_type) != "official":
        return results
    return sorted(results, key=_official_result_rank)


def _official_result_rank(result: dict[str, Any]) -> tuple[int, str]:
    detection = classify_source(
        {
            "requested_source_type": "official",
            "url": result.get("url"),
            "title": result.get("title"),
            "snippet": result.get("snippet"),
            "text": result.get("text") or result.get("snippet") or result.get("title"),
        }
    )
    detected = detection.get("detected_source_type")
    if detected == "official":
        rank = 0
    elif detected == "public_interaction" and detection.get("parent_official_domain"):
        rank = 1
    elif detected == "public_web":
        rank = 2
    elif detected in {"news", "forum", "public_social", "public_interaction"}:
        rank = 3
    else:
        rank = 4
    return (rank, str(result.get("url") or result.get("title") or ""))


def _official_detection_stats(results: list[dict[str, Any]], source_type: str) -> dict[str, Any]:
    if normalize_source_type(source_type) != "official":
        return {}
    detections = [
        classify_source(
            {
                "requested_source_type": "official",
                "url": result.get("url"),
                "title": result.get("title"),
                "snippet": result.get("snippet"),
                "text": result.get("text") or result.get("snippet") or result.get("title"),
            }
        )
        for result in results
    ]
    detected_counts = Counter(str(item.get("detected_source_type") or "unknown") for item in detections)
    top_domains = Counter(extract_domain(str(result.get("url") or "")) or "unknown" for result in results).most_common(5)
    detected_official_count = detected_counts.get("official", 0)
    failure_reason = ""
    if detected_official_count == 0:
        failure_reason = "no_results" if not results else "no_detected_official"
    return {
        "detected_official_count": detected_official_count,
        "detected_source_counts": dict(detected_counts),
        "top_domains": [domain for domain, _ in top_domains],
        "official_repair_failure_reason": failure_reason,
    }


def _round_sources(item: dict[str, Any]) -> list[str]:
    source_type = item.get("source_type")
    if source_type:
        return [normalize_source_type(source_type)]
    return normalize_source_scope(item.get("source_scope"))


def _dedupe_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for post in posts:
        key = _post_dedupe_key(post)
        if key in seen:
            continue
        seen.add(key)
        output.append(post)
    return output


def _post_dedupe_key(post: dict[str, Any]) -> str:
    event_id = str(post.get("event_id") or "")
    url = str(post.get("url") or "").strip()
    normalized_url = normalize_event_url(url)
    if normalized_url:
        return f"event_url:{event_id}:{normalized_url}"
    text = "".join(str(post.get("text") or "").split())[:300]
    if text:
        return f"text:{event_id}:" + hashlib.sha1(text.encode("utf-8")).hexdigest()
    return "raw_id:" + str(post.get("raw_id") or "")


def _event_url_key(event_id: str, url: str) -> tuple[str, str] | None:
    normalized_url = normalize_event_url(url)
    return (event_id, normalized_url) if normalized_url else None


def normalize_event_url(url: str) -> str:
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
    netloc = parts.netloc.lower()
    path = parts.path or ""
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(filtered_query, doseq=True), ""))


def _raw_post(event_id: str, query_round: dict[str, Any], source_type: str, result: dict[str, Any], text: str) -> dict[str, Any]:
    requested_source_type = normalize_source_type(source_type)
    raw_key = "|".join(
        [
            event_id,
            requested_source_type,
            str(query_round.get("round", 0)),
            str(query_round.get("query", "")),
            normalize_event_url(str(result.get("url") or "")) or str(result.get("title") or text[:80]),
        ]
    )
    raw_id = "raw_" + hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]
    raw = {
        "raw_id": raw_id,
        "event_id": event_id,
        "query": query_round["query"],
        "query_round": int(query_round.get("round", 0)),
        "requested_source_type": requested_source_type,
        "source_type": source_type,
        "source": source_type,
        "platform": result.get("platform") or "unknown",
        "publish_time": result.get("publish_time"),
        "url": result.get("url"),
        "title": result.get("title"),
        "text": text,
        "snippet": result.get("snippet"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    return enrich_record_source(raw)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False)]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def normalize_source_scope(value: Any, default_sources: list[str] | None = None) -> list[str]:
    sources = _as_list(value) or list(default_sources or DEFAULT_SOURCES)
    return _unique([normalize_source_type(source) for source in sources])


def normalize_source_type(source: Any) -> str:
    value = str(source).strip()
    return SOURCE_ALIASES.get(value.lower(), value)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item not in seen:
            output.append(item)
            seen.add(item)
    return output


def _dedupe_rounds(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    output: list[dict[str, Any]] = []
    for item in rounds:
        key = (str(item["query"]), int(item["round"]))
        if key not in seen:
            output.append(item)
            seen.add(key)
    return output


def _contains_source(source_counts: Counter[str], source: str) -> bool:
    source_lower = source.lower()
    return any(source_lower in key.lower() for key in source_counts)


def _any_contains(texts: list[str], needle: str) -> bool:
    needle = needle.lower()
    return any(needle in text for text in texts)


def _repair_reason(
    sources: list[str], stakeholders: list[str], stances: list[str], temporal: list[str], posts: list[dict[str, Any]]
) -> str:
    if not posts:
        return "no posts collected"
    parts = []
    if sources:
        parts.append("missing sources")
    if stakeholders:
        parts.append("missing stakeholders")
    if stances:
        parts.append("missing stances")
    if temporal:
        parts.append("missing temporal stages")
    return "; ".join(parts) if parts else "coverage sufficient"


def _coverage_snapshot(events: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "num_events": len(events),
        "events": events,
    }


def _coverage_missing_summary(coverage: dict[str, Any]) -> dict[str, Any]:
    return {
        "missing_sources": list(coverage.get("missing_sources") or []),
        "missing_stakeholders": list(coverage.get("missing_stakeholders") or []),
        "missing_stances": list(coverage.get("missing_stances") or []),
        "missing_temporal_stages": list(coverage.get("missing_temporal_stages") or []),
        "missing_raw_count": int(coverage.get("missing_raw_count") or 0),
        "need_query_repair": bool(coverage.get("need_query_repair")),
    }


def _repair_delta_summary(
    first_pass: dict[str, dict[str, Any]],
    second_pass: dict[str, dict[str, Any]],
    per_event_posts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    events = {}
    for event_id, before in first_pass.items():
        after = second_pass.get(event_id, before)
        before_missing = _coverage_missing_summary(before)
        after_missing = _coverage_missing_summary(after)
        events[event_id] = {
            "raw_posts": len(per_event_posts.get(event_id, [])),
            "missing_sources_before": before_missing["missing_sources"],
            "missing_sources_after": after_missing["missing_sources"],
            "missing_stakeholders_before": before_missing["missing_stakeholders"],
            "missing_stakeholders_after": after_missing["missing_stakeholders"],
            "missing_stances_before": before_missing["missing_stances"],
            "missing_stances_after": after_missing["missing_stances"],
            "missing_temporal_stages_before": before_missing["missing_temporal_stages"],
            "missing_temporal_stages_after": after_missing["missing_temporal_stages"],
            "need_query_repair_before": before_missing["need_query_repair"],
            "need_query_repair_after": after_missing["need_query_repair"],
        }
    return {"num_events": len(events), "events": events}


def _source_seconds(attempts: list[dict[str, Any]]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for attempt in attempts:
        totals[str(attempt.get("source_type") or "unknown")] += float(attempt.get("duration_seconds") or 0.0)
    return {source: round(seconds, 4) for source, seconds in totals.items()}


def _write_coverage_debug_artifacts(output_dir: Path, coverage_by_event: dict[str, dict[str, Any]]) -> None:
    source_rows: list[dict[str, Any]] = []
    stakeholder_rows: list[dict[str, Any]] = []
    stance_rows: list[dict[str, Any]] = []
    temporal_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for event_id, coverage in coverage_by_event.items():
        for row in coverage.get("source_detection", []):
            source_rows.append({"event_id": event_id, **row})
        for row in coverage.get("stakeholder_evidence", []):
            stakeholder_rows.append({"event_id": event_id, **row})
        for row in coverage.get("stance_evidence", []):
            stance_rows.append({"event_id": event_id, **row})
        for row in coverage.get("temporal_stage_evidence", []):
            temporal_rows.append({"event_id": event_id, **row})
        coverage_rows.extend(coverage_debug_rows(event_id, coverage))
    write_jsonl(output_dir / "source_detection_debug.jsonl", source_rows)
    write_jsonl(output_dir / "coverage_extraction_debug.jsonl", coverage_rows)
    _write_csv(
        output_dir / "stakeholder_evidence.csv",
        ["event_id", "stakeholder_type", "raw_id", "matched_text", "matched_rule", "source_type", "confidence", "rule_strength"],
        stakeholder_rows,
    )
    _write_csv(
        output_dir / "stance_evidence.csv",
        ["event_id", "stance_type", "raw_id", "matched_text", "matched_rule", "source_type", "confidence", "rule_strength"],
        stance_rows,
    )
    _write_csv(
        output_dir / "temporal_stage_evidence.csv",
        ["event_id", "stage_type", "raw_id", "matched_text", "matched_rule", "source_type", "confidence", "rule_strength"],
        temporal_rows,
    )


def _write_official_repair_artifacts(
    output_dir: Path,
    official_repair_queries: list[dict[str, Any]],
    repair_collection_summary: dict[str, Any],
) -> None:
    official_attempts = [
        attempt
        for attempt in repair_collection_summary.get("attempts", [])
        if attempt.get("source_type") == "official"
    ]
    candidate_rows = [
        {
            "event_id": attempt.get("event_id", ""),
            "query": attempt.get("query", ""),
            "query_template": _query_template_for_attempt(official_repair_queries, attempt),
            "provider": "search_client",
            "result_count": attempt.get("result_count", 0),
            "detected_official_count": attempt.get("detected_official_count", 0),
            "top_domains": "|".join(attempt.get("top_domains") or []),
            "failure_reason": attempt.get("official_repair_failure_reason", ""),
        }
        for attempt in official_attempts
    ]
    failure_rows = [row for row in candidate_rows if int(row.get("detected_official_count") or 0) == 0]
    summary = {
        "official_repair_queries": len(official_repair_queries),
        "official_repair_attempts": len(official_attempts),
        "detected_official_count": sum(int(row.get("detected_official_count") or 0) for row in candidate_rows),
        "failures": len(failure_rows),
        "events": _official_repair_events(candidate_rows),
    }
    _write_json(output_dir / "official_repair_summary.json", summary)
    _write_csv(
        output_dir / "official_source_candidates.csv",
        ["event_id", "query", "query_template", "provider", "result_count", "detected_official_count", "top_domains", "failure_reason"],
        candidate_rows,
    )
    _write_csv(
        output_dir / "official_repair_failure_report.csv",
        ["event_id", "query", "query_template", "provider", "result_count", "detected_official_count", "top_domains", "failure_reason"],
        failure_rows,
    )


def _query_template_for_attempt(queries: list[dict[str, Any]], attempt: dict[str, Any]) -> str:
    event_id = str(attempt.get("event_id") or "")
    query = str(attempt.get("query") or "")
    for item in queries:
        if str(item.get("event_id") or "") == event_id and str(item.get("query") or "") == query:
            return str(item.get("query_template") or "")
    return ""


def _write_low_raw_repair_summary(
    output_dir: Path,
    low_raw_repair_queries: list[dict[str, Any]],
    repair_collection_summary: dict[str, Any],
) -> None:
    low_queries = {(str(item.get("event_id") or ""), str(item.get("query") or ""), str(item.get("source_type") or "")) for item in low_raw_repair_queries}
    attempts = [
        attempt
        for attempt in repair_collection_summary.get("attempts", [])
        if (str(attempt.get("event_id") or ""), str(attempt.get("query") or ""), str(attempt.get("source_type") or "")) in low_queries
    ]
    events: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        event_id = str(attempt.get("event_id") or "")
        row = events.setdefault(event_id, {"attempts": 0, "written": 0, "failed_attempts": 0})
        row["attempts"] += 1
        row["written"] += int(attempt.get("written") or 0)
        if not attempt.get("ok"):
            row["failed_attempts"] += 1
    _write_json(
        output_dir / "low_raw_repair_summary.json",
        {
            "low_raw_repair_queries": len(low_raw_repair_queries),
            "low_raw_repair_attempts": len(attempts),
            "raw_posts_written": sum(int(attempt.get("written") or 0) for attempt in attempts),
            "events": events,
        },
    )


def _write_provider_error_summary(
    output_dir: Path,
    errors: list[dict[str, Any]],
    repair_collection_summary: dict[str, Any],
) -> None:
    rows = [
        {
            "event_id": error.get("event_id", ""),
            "query": error.get("query", ""),
            "source_type": error.get("source_type") or error.get("target_source") or "",
            "provider": error.get("provider", "search_client"),
            "error_type": error.get("error_type", ""),
            "duration_seconds": error.get("duration_seconds", ""),
            "retry_count": error.get("retry_count", ""),
            "final_status": error.get("final_status", "failed"),
        }
        for error in errors
    ]
    for event in repair_collection_summary.get("events", {}).values():
        for attempt in [*event.get("first_pass_attempts", []), *event.get("repair_attempts", [])]:
            if attempt.get("ok") is False:
                rows.append(
                    {
                        "event_id": attempt.get("event_id", ""),
                        "query": attempt.get("query", ""),
                        "source_type": attempt.get("source_type", ""),
                        "provider": attempt.get("provider", "search_client"),
                        "error_type": attempt.get("error_type", ""),
                        "duration_seconds": attempt.get("duration_seconds", ""),
                        "retry_count": attempt.get("retry_count", ""),
                        "final_status": attempt.get("final_status", "failed"),
                    }
                )
    _write_csv(
        output_dir / "provider_error_summary.csv",
        ["event_id", "query", "source_type", "provider", "error_type", "duration_seconds", "retry_count", "final_status"],
        rows,
    )


def _write_provider_attempt_summary(output_dir: Path, repair_collection_summary: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for event in repair_collection_summary.get("events", {}).values():
        for phase, attempts in (
            ("first_pass", event.get("first_pass_attempts", [])),
            ("repair", event.get("repair_attempts", [])),
        ):
            for attempt in attempts:
                provider_attempts = list(attempt.get("provider_attempts") or [])
                if not provider_attempts:
                    provider_attempts = [
                        {
                            "attempt": 1,
                            "ok": bool(attempt.get("ok")),
                            "error_type": attempt.get("error_type"),
                            "error": attempt.get("error"),
                            "duration_seconds": attempt.get("duration_seconds"),
                            "final_status": attempt.get("final_status") or ("success" if attempt.get("ok") else "failed"),
                        }
                    ]
                for provider_attempt in provider_attempts:
                    rows.append(
                        {
                            "event_id": attempt.get("event_id", ""),
                            "query": attempt.get("query", ""),
                            "source_type": attempt.get("source_type", ""),
                            "provider": attempt.get("provider", "search_client"),
                            "phase": phase,
                            "attempt": provider_attempt.get("attempt", ""),
                            "ok": provider_attempt.get("ok", ""),
                            "error_type": provider_attempt.get("error_type", ""),
                            "duration_seconds": provider_attempt.get("duration_seconds", ""),
                            "final_status": provider_attempt.get("final_status", ""),
                        }
                    )
    _write_csv(
        output_dir / "provider_attempt_summary.csv",
        ["event_id", "query", "source_type", "provider", "phase", "attempt", "ok", "error_type", "duration_seconds", "final_status"],
        rows,
    )


def _official_repair_events(candidate_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        event_id = str(row.get("event_id") or "")
        event = events.setdefault(event_id, {"attempts": 0, "detected_official_count": 0, "failure_reasons": []})
        event["attempts"] += 1
        event["detected_official_count"] += int(row.get("detected_official_count") or 0)
        if row.get("failure_reason"):
            event["failure_reasons"].append(row["failure_reason"])
    return events


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _merge_existing_query_plans(path: Path, generated_plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not path.exists():
        return generated_plans
    existing_plans = _read_existing_jsonl(path)
    existing_by_event: dict[str, dict[str, Any]] = {}
    for plan in existing_plans:
        event_id = str(plan.get("event_id", ""))
        if event_id and event_id not in existing_by_event:
            existing_by_event[event_id] = plan
    merged: list[dict[str, Any]] = []
    for plan in generated_plans:
        event_id = str(plan.get("event_id", ""))
        merged.append(existing_by_event.get(event_id, plan))
    return merged


def _read_existing_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def _read_existing_repair_collection_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"events": {}, "attempts": []}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"events": {}, "attempts": []}
    if not isinstance(payload, dict):
        return {"events": {}, "attempts": []}
    payload.setdefault("events", {})
    payload.setdefault("attempts", [])
    return payload


def _read_existing_coverage_errors(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, dict):
        return []
    errors = payload.get("provider_errors", payload.get("errors", []))
    return list(errors) if isinstance(errors, list) else []


def _read_completed_event_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError(f"{path} must contain a JSON object")
    events = report.get("events")
    if not isinstance(events, dict):
        return set()
    return {str(event_id) for event_id in events if str(event_id)}


def _group_posts_by_event(posts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for post in posts:
        event_id = str(post.get("event_id", ""))
        if event_id:
            grouped.setdefault(event_id, []).append(post)
    return grouped


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"collector config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _count_event_duplicate_raw_ids(per_event_posts: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    duplicates: dict[str, int] = {}
    for event_id, posts in per_event_posts.items():
        raw_ids = [str(row.get("raw_id", "")).strip() for row in posts if str(row.get("raw_id", "")).strip()]
        seen: set[str] = set()
        event_dupes = 0
        for raw_id in raw_ids:
            if raw_id in seen:
                event_dupes += 1
            else:
                seen.add(raw_id)
        if event_dupes:
            duplicates[event_id] = event_dupes
    return duplicates


def _count_event_url_pairs(per_event_posts: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    duplicates: dict[str, int] = {}
    for event_id, posts in per_event_posts.items():
        pairs = [
            normalize_event_url(str(row.get("url") or ""))
            for row in posts
            if normalize_event_url(str(row.get("url") or ""))
        ]
        seen: set[str] = set()
        event_dupes = 0
        for pair in pairs:
            if pair in seen:
                event_dupes += 1
            else:
                seen.add(pair)
        if event_dupes:
            duplicates[event_id] = event_dupes
    return duplicates


def _find_official_missing_events(
    events: list[dict[str, Any]],
    per_event_posts: dict[str, list[dict[str, Any]]],
    event_reports: dict[str, dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for event in events:
        event_id = str(event.get("event_id", ""))
        expected_sources = _planner_normalize_source_scope(event.get("source_scope"))
        if "official" not in expected_sources:
            continue
        coverage = event_reports.get(event_id, {})
        source_counts = coverage.get("source_counts", {})
        if source_counts.get("official", 0) == 0:
            missing.append(event_id)
    return missing


def _find_interaction_missing_events(
    events: list[dict[str, Any]],
    per_event_posts: dict[str, list[dict[str, Any]]],
    event_reports: dict[str, dict[str, Any]],
) -> list[str]:
    interaction_sources = {"public_interaction", "forum", "public_social"}
    missing: list[str] = []
    for event in events:
        event_id = str(event.get("event_id", ""))
        expected_sources = set(_planner_normalize_source_scope(event.get("source_scope")))
        relevant = expected_sources & interaction_sources
        if not relevant:
            continue
        coverage = event_reports.get(event_id, {})
        source_counts = coverage.get("source_counts", {})
        if all(source_counts.get(source, 0) == 0 for source in relevant):
            missing.append(event_id)
    return missing


def _count_duplicate_plan_event_ids(query_plans: list[dict[str, Any]]) -> dict[str, int]:
    from collections import Counter

    event_ids = [str(plan.get("event_id", "")).strip() for plan in query_plans if str(plan.get("event_id", "")).strip()]
    return {event_id: count for event_id, count in Counter(event_ids).items() if count > 1}


def _read_existing_coverage_provider_warnings(path: Path) -> list[dict[str, Any]]:
    """Read provider_warnings from existing coverage.json for resume/merge."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, dict):
        return []
    warnings_list = payload.get("provider_warnings", payload.get("provider_errors", payload.get("errors", [])))
    return list(warnings_list) if isinstance(warnings_list, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
