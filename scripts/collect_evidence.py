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

import yaml

from episoa.collector.search_client import SearchClient, load_search_config
from episoa.data.loader import read_jsonl, write_jsonl


DEFAULT_EVENTS_PATH = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_CONFIG_PATH = Path("configs/collector.yaml")
DEFAULT_RAW_POSTS_PATH = Path("data/pubevent_soa_lite/raw/raw_posts.jsonl")
DEFAULT_INTERIM_DIR = Path("data/pubevent_soa_lite/interim")
DEFAULT_QUERY_PLAN_PATH = DEFAULT_INTERIM_DIR / "query_plan.jsonl"
DEFAULT_COVERAGE_REPORT_PATH = DEFAULT_INTERIM_DIR / "collection_coverage_report.json"
DEFAULT_RECOLLECTION_DEBUG_PATH = DEFAULT_INTERIM_DIR / "recollection_debug_report.json"

DEFAULT_SOURCES = ["news", "official", "public_interaction", "forum", "public_social", "public_web"]
SOURCE_ALIASES = {"social_media": "public_social"}
DEFAULT_TEMPORAL_STAGES = ["before", "during", "after"]


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
    parser.add_argument("--recollection", action="store_true", help="Read recollection_plan.jsonl rows instead of full event configs.")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-queries-per-event", type=int, default=6)
    parser.add_argument("--debug-output", default=str(DEFAULT_RECOLLECTION_DEBUG_PATH))
    return parser


def collect_from_cli(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    config_path = Path(args.config)
    output_path = Path(args.output)
    query_plan_path = Path(args.query_plan_output)
    coverage_path = Path(args.coverage_output)
    debug_path = Path(args.debug_output)
    if args.recollection and args.query_plan_output == str(DEFAULT_QUERY_PLAN_PATH):
        query_plan_path = DEFAULT_INTERIM_DIR / "recollection_query_plan.jsonl"
    if args.recollection and args.coverage_output == str(DEFAULT_COVERAGE_REPORT_PATH):
        coverage_path = DEFAULT_INTERIM_DIR / "recollection_coverage_report.json"

    config = _load_yaml(config_path)
    search_config = load_search_config(dict(config.get("search", {})))
    collector_config = dict(config.get("collector", {}))
    default_sources = normalize_source_scope(collector_config.get("source_types") or DEFAULT_SOURCES)
    max_results_per_query = int(collector_config.get("max_results_per_query", 10))
    max_evidence_per_event = int(collector_config.get("max_evidence_per_event", 50))
    sleep_seconds = float(collector_config.get("sleep_seconds", 0.5))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    query_plan_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.parent.mkdir(parents=True, exist_ok=True)
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
            coverage_path,
            {
                "status": "blocked",
                "collection_skipped_reason": str(exc),
                "events_path": str(events_path),
            },
        )
        print(f"WARNING: {exc}")
        return 1

    query_plans = [
        plan_recollection_queries(event, default_sources=default_sources)
        if args.recollection
        else plan_event_queries(event, default_sources=default_sources)
        for event in events
    ]
    write_jsonl(query_plan_path, query_plans)

    if not events:
        write_jsonl(output_path, [])
        if args.recollection:
            write_debug_report(debug_path, init_debug_report(0), output_path)
        _write_json(
            coverage_path,
            {
                "status": "blocked",
                "collection_skipped_reason": "events.jsonl is empty",
                "planned_only": True,
                "num_events": 0,
            },
        )
        print("WARNING: events.jsonl is empty; no raw posts were collected.")
        return 0

    if not search_config.configured:
        for plan in query_plans:
            plan["planned_only"] = True
        write_jsonl(query_plan_path, query_plans)
        write_jsonl(output_path, [])
        if args.recollection:
            debug = init_debug_report(len(events))
            debug["queries_generated"] = sum(min(len(plan["query_rounds"]), args.max_queries_per_event) for plan in query_plans)
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
        debug["queries_generated"] = sum(min(len(plan["query_rounds"]), args.max_queries_per_event) for plan in query_plans)
        per_event_posts, errors = collect_recollection_streaming(
            client=client,
            events=events,
            query_plans=query_plans,
            output_path=output_path,
            max_results_per_query=max_results_per_query,
            max_evidence_per_event=max_evidence_per_event,
            sleep_seconds=sleep_seconds,
            max_queries_per_event=args.max_queries_per_event,
            debug=debug,
            debug_path=debug_path,
        )
        write_jsonl(query_plan_path, query_plans)
        report = build_coverage_report(events, per_event_posts, errors, default_sources=default_sources)
        _write_json(coverage_path, report)
        write_debug_report(debug_path, debug, output_path)
        print(f"Collected {debug['raw_posts_collected']} recollection raw posts into {output_path}")
        return 0

    all_posts: list[dict[str, Any]] = []
    per_event_posts: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []

    for event, plan in zip(events, query_plans, strict=True):
        event_posts = _collect_for_plan(
            client,
            event,
            plan,
            max_results_per_query=max_results_per_query,
            max_evidence_per_event=max_evidence_per_event,
            sleep_seconds=sleep_seconds,
            errors=errors,
        )
        coverage = evaluate_coverage(event, event_posts, default_sources=default_sources)
        repair_round = 1
        while coverage["need_query_repair"] and repair_round <= 2 and len(event_posts) < max_evidence_per_event:
            repair_rounds = build_repair_rounds(event, coverage, repair_round, default_sources=default_sources)
            plan["query_rounds"].extend(repair_rounds)
            plan["repair_keywords"].extend([item["query"] for item in repair_rounds])
            event_posts.extend(
                _collect_rounds(
                    client,
                    event,
                    repair_rounds,
                    max_results_per_query=max_results_per_query,
                    remaining=max_evidence_per_event - len(event_posts),
                    sleep_seconds=sleep_seconds,
                    errors=errors,
                )
            )
            coverage = evaluate_coverage(event, event_posts, default_sources=default_sources)
            repair_round += 1
        per_event_posts[str(event.get("event_id", ""))] = event_posts
        all_posts.extend(event_posts)

    write_jsonl(output_path, all_posts)
    write_jsonl(query_plan_path, query_plans)
    report = build_coverage_report(events, per_event_posts, errors, default_sources=default_sources)
    _write_json(coverage_path, report)
    print(f"Collected {len(all_posts)} raw posts into {output_path}")
    return 0


def plan_event_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event.get("event_description") or event.get("query") or event_id)
    seed_keywords = _as_list(event.get("seed_keywords") or event.get("queries") or event.get("query") or event_name)
    stakeholders = _as_list(event.get("stakeholder_hints"))
    stances = _as_list(event.get("stance_hints"))
    source_scope = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    temporal_stages = _as_list(event.get("temporal_stages")) or _as_list(event.get("time_window")) or DEFAULT_TEMPORAL_STAGES

    expanded_keywords = _unique(
        seed_keywords
        + [f"{keyword} {stakeholder}" for keyword in seed_keywords for stakeholder in stakeholders]
        + [f"{keyword} {stance}" for keyword in seed_keywords for stance in stances]
    )
    query_rounds: list[dict[str, Any]] = []
    for query in _unique(seed_keywords + expanded_keywords):
        query_rounds.append(
            {
                "round": 0,
                "query": query,
                "source_scope": source_scope,
                "target_stakeholder": None,
                "target_stance": None,
                "target_temporal_stage": None,
                "reason": "seed_or_expanded_keyword",
                "generated_by": "cfsm_s1_query_planning",
                "used_for_collection": True,
            }
        )
    return {
        "event_id": event_id,
        "event_name": event_name,
        "seed_keywords": seed_keywords,
        "expanded_keywords": [item for item in expanded_keywords if item not in seed_keywords],
        "repair_keywords": [],
        "query_rounds": query_rounds,
    }


def plan_recollection_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event_id)
    repair_keywords = _as_list(event.get("repair_keywords") or event.get("seed_keywords") or event.get("query") or event_name)
    source_scope = normalize_source_scope(event.get("target_sources") or event.get("source_scope"), default_sources=default_sources)
    site_scope = _as_list(event.get("site_scope"))
    query_rounds: list[dict[str, Any]] = []
    for query in repair_keywords:
        scoped_queries = [query]
        scoped_queries.extend([f"site:{site} {query}" for site in site_scope if "." in site])
        for scoped_query in _unique(scoped_queries):
            query_rounds.append(
                {
                    "round": 0,
                    "query": scoped_query,
                    "source_scope": source_scope,
                    "target_stakeholder": None,
                    "target_stance": None,
                    "target_temporal_stage": None,
                    "reason": "; ".join(_as_list(event.get("reason"))) or "targeted recollection",
                    "generated_by": "quality_filter_recollection_plan",
                    "used_for_collection": True,
                }
            )
    return {
        "event_id": event_id,
        "event_name": event_name,
        "seed_keywords": [],
        "expanded_keywords": [],
        "repair_keywords": repair_keywords,
        "query_rounds": query_rounds,
    }


def evaluate_coverage(
    event: dict[str, Any], posts: list[dict[str, Any]], default_sources: list[str] | None = None
) -> dict[str, Any]:
    source_scope = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    stakeholders = _as_list(event.get("stakeholder_hints"))
    stances = _as_list(event.get("stance_hints"))
    temporal_stages = _as_list(event.get("temporal_stages")) or DEFAULT_TEMPORAL_STAGES

    combined_texts = [f"{post.get('title', '')} {post.get('snippet', '')} {post.get('text', '')}".lower() for post in posts]
    source_counts = Counter(str(post.get("source") or post.get("platform") or "unknown") for post in posts)
    source_coverage = {source: _contains_source(source_counts, source) for source in source_scope}
    stakeholder_coverage = {item: _any_contains(combined_texts, item) for item in stakeholders}
    stance_coverage = {item: _any_contains(combined_texts, item) for item in stances}
    temporal_stage_coverage = {item: _any_contains(combined_texts, item) for item in temporal_stages}
    urls = [post.get("url") for post in posts if post.get("url")]
    duplicate_urls = len(urls) - len(set(urls))

    missing_sources = [key for key, covered in source_coverage.items() if not covered]
    missing_stakeholders = [key for key, covered in stakeholder_coverage.items() if not covered]
    missing_stances = [key for key, covered in stance_coverage.items() if not covered]
    missing_temporal = [key for key, covered in temporal_stage_coverage.items() if not covered]
    need_repair = bool(posts) and bool(missing_sources or missing_stakeholders or missing_stances or missing_temporal)
    if not posts:
        need_repair = True
    return {
        "source_coverage": source_coverage,
        "stakeholder_coverage": stakeholder_coverage,
        "stance_coverage": stance_coverage,
        "temporal_stage_coverage": temporal_stage_coverage,
        "traceability_rate": (len(urls) / len(posts)) if posts else 0.0,
        "redundancy_rate": (duplicate_urls / len(posts)) if posts else 0.0,
        "missing_sources": missing_sources,
        "missing_stakeholders": missing_stakeholders,
        "missing_stances": missing_stances,
        "missing_temporal_stages": missing_temporal,
        "need_query_repair": need_repair,
        "repair_reason": _repair_reason(missing_sources, missing_stakeholders, missing_stances, missing_temporal, posts),
    }


def build_repair_rounds(
    event: dict[str, Any], coverage: dict[str, Any], repair_round: int, default_sources: list[str] | None = None
) -> list[dict[str, Any]]:
    base = _as_list(event.get("seed_keywords") or event.get("query") or event.get("event_name") or event.get("event_id"))
    source_scope = coverage["missing_sources"] or normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    repair_targets: list[tuple[str | None, str | None, str | None, str]] = []
    for source in coverage["missing_sources"]:
        repair_targets.append((None, None, None, f"missing source: {source}"))
    for stakeholder in coverage["missing_stakeholders"]:
        repair_targets.append((stakeholder, None, None, f"missing stakeholder: {stakeholder}"))
    for stance in coverage["missing_stances"]:
        repair_targets.append((None, stance, None, f"missing stance: {stance}"))
    for stage in coverage["missing_temporal_stages"]:
        repair_targets.append((None, None, stage, f"missing temporal stage: {stage}"))
    if not repair_targets:
        repair_targets.append((None, None, None, "no posts collected"))

    rounds: list[dict[str, Any]] = []
    for keyword in base:
        for stakeholder, stance, stage, reason in repair_targets:
            parts = [keyword, stakeholder, stance, stage]
            query = " ".join([str(part) for part in parts if part])
            rounds.append(
                {
                    "round": repair_round,
                    "query": query,
                    "source_scope": source_scope,
                    "target_stakeholder": stakeholder,
                    "target_stance": stance,
                    "target_temporal_stage": stage,
                    "reason": reason,
                    "generated_by": "cfsm_s6_query_repair",
                    "used_for_collection": True,
                }
            )
    return _dedupe_rounds(rounds)


def build_coverage_report(
    events: list[dict[str, Any]],
    per_event_posts: dict[str, list[dict[str, Any]]],
    errors: list[dict[str, Any]],
    default_sources: list[str] | None = None,
) -> dict[str, Any]:
    event_reports = {}
    for event in events:
        event_id = str(event.get("event_id", ""))
        event_reports[event_id] = evaluate_coverage(event, per_event_posts.get(event_id, []), default_sources=default_sources)
    return {
        "status": "completed_with_errors" if errors else "completed",
        "num_events": len(events),
        "num_raw_posts": sum(len(items) for items in per_event_posts.values()),
        "events": event_reports,
        "errors": errors,
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
            seen_urls: set[str] = set()
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
                    results = response["results"]
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
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
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
    sleep_seconds: float,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _collect_rounds(
        client,
        event,
        list(plan["query_rounds"]),
        max_results_per_query=max_results_per_query,
        remaining=max_evidence_per_event,
        sleep_seconds=sleep_seconds,
        errors=errors,
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
) -> list[dict[str, Any]]:
    event_id = str(event.get("event_id", ""))
    posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in rounds:
        if len(posts) >= remaining:
            break
        source_scope = normalize_source_scope(item.get("source_scope"))
        for source_type in source_scope:
            if len(posts) >= remaining:
                break
            try:
                results = client.search(
                    query=str(item["query"]),
                    max_results=max_results_per_query,
                    source_type=str(source_type),
                    time_window=event.get("time_window"),
                )
            except RuntimeError as exc:
                errors.append({"event_id": event_id, "query": item["query"], "source_type": source_type, "error": str(exc)})
                continue
            for result in results:
                text = str(result.get("text") or result.get("snippet") or result.get("title") or "").strip()
                if not text:
                    continue
                url = str(result.get("url") or "").strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                posts.append(_raw_post(event_id, item, source_type, result, text))
                if len(posts) >= remaining:
                    break
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    return posts


def _raw_post(event_id: str, query_round: dict[str, Any], source_type: str, result: dict[str, Any], text: str) -> dict[str, Any]:
    source_type = normalize_source_type(source_type)
    raw_key = "|".join(
        [
            event_id,
            str(query_round.get("round", 0)),
            str(query_round.get("query", "")),
            str(result.get("url") or result.get("title") or text[:80]),
        ]
    )
    raw_id = "raw_" + hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]
    return {
        "raw_id": raw_id,
        "event_id": event_id,
        "query": query_round["query"],
        "query_round": int(query_round.get("round", 0)),
        "source": source_type,
        "platform": result.get("platform") or "unknown",
        "publish_time": result.get("publish_time"),
        "url": result.get("url"),
        "title": result.get("title"),
        "text": text,
        "snippet": result.get("snippet"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


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


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"collector config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
