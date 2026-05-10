"""Run a paired heuristic-vs-GA query planner ablation for C-FSM collection."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from episoa.collector.genetic_query_planner import GeneticPlannerConfig, ProbeCache, plan_event_queries_ga
from episoa.collector.query_planner import anchor_entity_terms, normalize_source_scope, plan_event_queries
from episoa.collector.search_client import SearchClient, load_search_config
from episoa.data.loader import read_jsonl
from episoa.data.validator import validate_formal_event_record

import importlib.util


ROOT = Path(__file__).resolve().parents[1]
COLLECT_SCRIPT_PATH = ROOT / "scripts" / "collect_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_evidence_script", COLLECT_SCRIPT_PATH)
collect_evidence_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collect_evidence_script)


PER_EVENT_COLUMNS = [
    "event_id",
    "condition",
    "initial_source_coverage",
    "initial_entity_coverage",
    "initial_traceability_rate",
    "initial_redundancy_rate",
    "initial_need_query_repair",
    "initial_missing_sources",
    "initial_missing_entities",
    "initial_missing_stakeholders",
    "initial_missing_stances",
    "final_source_coverage",
    "final_entity_coverage",
    "final_traceability_rate",
    "final_redundancy_rate",
    "num_raw_posts",
    "num_repair_rounds",
    "num_repair_queries",
    "total_collection_queries",
    "total_api_calls",
    "probe_api_calls",
    "cache_hits",
    "cache_misses",
    "repair_api_calls",
    "evidence_per_api_call",
    "coverage_gain_per_api_call",
]

NUMERIC_METRICS = [
    "initial_source_coverage",
    "initial_entity_coverage",
    "initial_traceability_rate",
    "initial_redundancy_rate",
    "initial_need_query_repair",
    "final_source_coverage",
    "final_entity_coverage",
    "final_traceability_rate",
    "final_redundancy_rate",
    "num_raw_posts",
    "num_repair_rounds",
    "num_repair_queries",
    "total_collection_queries",
    "total_api_calls",
    "probe_api_calls",
    "cache_hits",
    "cache_misses",
    "repair_api_calls",
    "evidence_per_api_call",
    "coverage_gain_per_api_call",
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_ablation(
        config_path=Path(args.config),
        events_path=Path(args.events),
        output_dir=Path(args.output_dir),
        max_events=args.max_events,
        event_ids=_split_ids(args.event_ids),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare heuristic and GA query planning for C-FSM collection.")
    parser.add_argument("--config", default="configs/collector.yaml")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--output-dir", default="outputs/runs/query_planner_ablation")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--event-ids", default=None, help="Comma-separated event_ids to evaluate.")
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic fixture search instead of live search.")
    return parser


def run_ablation(
    *,
    config_path: Path,
    events_path: Path,
    output_dir: Path,
    max_events: int | None = None,
    event_ids: set[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config = _load_yaml(config_path)
    collector_config = dict(config.get("collector", {}))
    search_config = load_search_config(dict(config.get("search", {})))
    events = _load_valid_events(events_path, max_events=max_events, event_ids=event_ids)
    if not events:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "status": "blocked",
            "blocked_reason": "no valid formal events selected",
            "num_events": 0,
            "dry_run": dry_run,
        }
        _write_json(output_dir / "query_planner_ablation_summary.json", summary)
        return summary
    if not dry_run and not search_config.configured:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "status": "blocked",
            "blocked_reason": "search API is not configured; use --dry-run for fixture evaluation",
            "num_events": len(events),
            "dry_run": dry_run,
        }
        _write_json(output_dir / "query_planner_ablation_summary.json", summary)
        return summary

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for condition in ("heuristic", "ga"):
        client = CountingSearchClient(FixtureSearchClient() if dry_run else SearchClient(search_config))
        rows.extend(
            _run_condition(
                condition=condition,
                events=events,
                collector_config=collector_config,
                client=client,
            )
        )

    per_event_path = output_dir / "query_planner_ablation_per_event.csv"
    summary_csv_path = output_dir / "query_planner_ablation_summary.csv"
    summary_json_path = output_dir / "query_planner_ablation_summary.json"
    _write_csv(per_event_path, rows, PER_EVENT_COLUMNS)
    summary_rows, summary_json = _summarize(rows)
    summary_json.update(
        {
            "status": "completed",
            "num_events": len(events),
            "dry_run": dry_run,
            "per_event_path": str(per_event_path),
            "summary_csv_path": str(summary_csv_path),
        }
    )
    _write_csv(summary_csv_path, summary_rows, ["condition", *NUMERIC_METRICS])
    _write_json(summary_json_path, summary_json)
    return summary_json


def _run_condition(
    *,
    condition: str,
    events: list[dict[str, Any]],
    collector_config: dict[str, Any],
    client: "CountingSearchClient",
) -> list[dict[str, Any]]:
    default_sources = normalize_source_scope(collector_config.get("source_types"))
    max_results_per_query = int(collector_config.get("max_results_per_query", 10))
    max_evidence_per_event = int(collector_config.get("max_evidence_per_event", 50))
    planner_config = dict(collector_config.get("query_planner") or {})
    ga_config = GeneticPlannerConfig.from_dict({**dict(planner_config.get("ga") or {}), "enabled": True})
    rows = []
    ga_cache = ProbeCache()
    for event in events:
        probe_start = client.search_with_debug_calls
        cache_stats_before = ga_cache.stats()
        if condition == "ga":
            plan, planner_debug = plan_event_queries_ga(
                event,
                client=client,
                default_sources=default_sources,
                config=ga_config,
                cache=ga_cache,
            )
        else:
            plan = plan_event_queries(event, default_sources=default_sources)
            planner_debug = {"cache_stats": {"hits": 0, "misses": 0}}
        probe_api_calls = client.search_with_debug_calls - probe_start
        cache_stats_after = planner_debug.get("cache_stats") or {}
        cache_hits = int(cache_stats_after.get("hits", 0)) - int(cache_stats_before.get("hits", 0))
        cache_misses = int(cache_stats_after.get("misses", 0)) - int(cache_stats_before.get("misses", 0))
        initial_start = client.search_calls
        errors: list[dict[str, Any]] = []
        initial_posts = collect_evidence_script._collect_for_plan(
            client,
            event,
            plan,
            max_results_per_query=max_results_per_query,
            max_evidence_per_event=max_evidence_per_event,
            sleep_seconds=0,
            errors=errors,
        )
        initial_collection_api_calls = client.search_calls - initial_start
        initial_coverage = _coverage_metrics(event, initial_posts, default_sources)
        event_posts = list(initial_posts)
        repair_round = 1
        num_repair_rounds = 0
        num_repair_queries = 0
        repair_api_calls = 0
        coverage = collect_evidence_script.evaluate_coverage(event, event_posts, default_sources=default_sources)
        while coverage["need_query_repair"] and repair_round <= 2 and len(event_posts) < max_evidence_per_event:
            repair_rounds = collect_evidence_script.build_repair_rounds(
                event, coverage, repair_round, default_sources=default_sources
            )
            plan["query_rounds"].extend(repair_rounds)
            plan["repair_keywords"].extend([item["query"] for item in repair_rounds])
            num_repair_rounds += 1
            num_repair_queries += len(repair_rounds)
            repair_start = client.search_calls
            event_posts.extend(
                collect_evidence_script._collect_rounds(
                    client,
                    event,
                    repair_rounds,
                    max_results_per_query=max_results_per_query,
                    remaining=max_evidence_per_event - len(event_posts),
                    sleep_seconds=0,
                    errors=errors,
                )
            )
            repair_api_calls += client.search_calls - repair_start
            coverage = collect_evidence_script.evaluate_coverage(event, event_posts, default_sources=default_sources)
            repair_round += 1

        final_coverage = _coverage_metrics(event, event_posts, default_sources)
        total_collection_queries = len(plan["query_rounds"])
        total_api_calls = probe_api_calls + initial_collection_api_calls + repair_api_calls
        coverage_gain = final_coverage["source_coverage_rate"] - initial_coverage["source_coverage_rate"]
        rows.append(
            {
                "event_id": event.get("event_id"),
                "condition": condition,
                "initial_source_coverage": initial_coverage["source_coverage_rate"],
                "initial_entity_coverage": initial_coverage["entity_coverage_rate"],
                "initial_traceability_rate": initial_coverage["traceability_rate"],
                "initial_redundancy_rate": initial_coverage["redundancy_rate"],
                "initial_need_query_repair": initial_coverage["need_query_repair"],
                "initial_missing_sources": "|".join(initial_coverage["missing_sources"]),
                "initial_missing_entities": "|".join(initial_coverage["missing_entities"]),
                "initial_missing_stakeholders": "|".join(initial_coverage["missing_stakeholders"]),
                "initial_missing_stances": "|".join(initial_coverage["missing_stances"]),
                "final_source_coverage": final_coverage["source_coverage_rate"],
                "final_entity_coverage": final_coverage["entity_coverage_rate"],
                "final_traceability_rate": final_coverage["traceability_rate"],
                "final_redundancy_rate": final_coverage["redundancy_rate"],
                "num_raw_posts": len(event_posts),
                "num_repair_rounds": num_repair_rounds,
                "num_repair_queries": num_repair_queries,
                "total_collection_queries": total_collection_queries,
                "total_api_calls": total_api_calls,
                "probe_api_calls": probe_api_calls,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "repair_api_calls": repair_api_calls,
                "evidence_per_api_call": _safe_divide(len(event_posts), total_api_calls),
                "coverage_gain_per_api_call": _safe_divide(coverage_gain, total_api_calls),
            }
        )
    return rows


def _coverage_metrics(event: dict[str, Any], posts: list[dict[str, Any]], default_sources: list[str]) -> dict[str, Any]:
    coverage = collect_evidence_script.evaluate_coverage(event, posts, default_sources=default_sources)
    source_values = list((coverage.get("source_coverage") or {}).values())
    entity_terms = anchor_entity_terms(event)
    missing_entities = _missing_terms(posts, entity_terms)
    return {
        "source_coverage_rate": _safe_divide(sum(1 for item in source_values if item), len(source_values)),
        "entity_coverage_rate": _safe_divide(len(entity_terms) - len(missing_entities), len(entity_terms)),
        "traceability_rate": coverage.get("traceability_rate", 0.0),
        "redundancy_rate": coverage.get("redundancy_rate", 0.0),
        "need_query_repair": coverage.get("need_query_repair", False),
        "missing_sources": list(coverage.get("missing_sources") or []),
        "missing_entities": missing_entities,
        "missing_stakeholders": list(coverage.get("missing_stakeholders") or []),
        "missing_stances": list(coverage.get("missing_stances") or []),
    }


def _missing_terms(posts: list[dict[str, Any]], terms: list[str]) -> list[str]:
    texts = [f"{post.get('title', '')} {post.get('snippet', '')} {post.get('text', '')}".lower() for post in posts]
    return [term for term in terms if not any(term.lower() in text for text in texts)]


def _summarize(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_condition = {condition: [row for row in rows if row["condition"] == condition] for condition in ("heuristic", "ga")}
    summary_rows = []
    summary_json: dict[str, Any] = {"conditions": {}, "paired_differences": {}}
    for condition, condition_rows in by_condition.items():
        aggregate = {"condition": condition}
        for metric in NUMERIC_METRICS:
            aggregate[metric] = _mean([float(row[metric]) for row in condition_rows])
        summary_rows.append(aggregate)
        summary_json["conditions"][condition] = {metric: aggregate[metric] for metric in NUMERIC_METRICS}
    paired = _paired_differences(rows)
    diff_row = {"condition": "ga_minus_heuristic", **paired}
    summary_rows.append(diff_row)
    summary_json["paired_differences"] = paired
    return summary_rows, summary_json


def _paired_differences(rows: list[dict[str, Any]]) -> dict[str, float]:
    by_event: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_event.setdefault(str(row["event_id"]), {})[str(row["condition"])] = row
    diffs: dict[str, float] = {}
    for metric in NUMERIC_METRICS:
        values = []
        for condition_rows in by_event.values():
            if "ga" in condition_rows and "heuristic" in condition_rows:
                values.append(float(condition_rows["ga"][metric]) - float(condition_rows["heuristic"][metric]))
        diffs[metric] = _mean(values)
    return diffs


class CountingSearchClient:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.search_calls = 0
        self.search_with_debug_calls = 0

    def search(self, *, query: str, max_results: int, source_type: str | None = None, time_window: Any = None) -> list[dict[str, Any]]:
        self.search_calls += 1
        return self.client.search(query=query, max_results=max_results, source_type=source_type, time_window=time_window)

    def search_with_debug(
        self, *, query: str, max_results: int, source_type: str | None = None, time_window: Any = None
    ) -> dict[str, Any]:
        self.search_with_debug_calls += 1
        return self.client.search_with_debug(query=query, max_results=max_results, source_type=source_type, time_window=time_window)


class FixtureSearchClient:
    def search(self, *, query: str, max_results: int, source_type: str | None = None, time_window: Any = None) -> list[dict[str, Any]]:
        return self.search_with_debug(
            query=query, max_results=max_results, source_type=source_type, time_window=time_window
        )["results"]

    def search_with_debug(
        self, *, query: str, max_results: int, source_type: str | None = None, time_window: Any = None
    ) -> dict[str, Any]:
        source = str(source_type or "public_web")
        base = f"{query} {source}"
        results = [
            {
                "title": base,
                "snippet": f"{base} public response support concern",
                "text": f"{base} agency residents project trigger conflict response resolution",
                "url": f"https://fixture.test/{source}/{_stable_id(query)}",
                "source": source,
                "platform": source,
            }
        ][:max_results]
        return {"ok": True, "error": None, "error_type": None, "results": results, "result_count": len(results)}


def _load_valid_events(events_path: Path, *, max_events: int | None, event_ids: set[str] | None) -> list[dict[str, Any]]:
    events = read_jsonl(events_path)
    if event_ids:
        events = [event for event in events if str(event.get("event_id")) in event_ids]
    if max_events is not None:
        events = events[:max_events]
    errors = [
        error
        for index, event in enumerate(events, start=1)
        for error in validate_formal_event_record(event, f"events:{index}")
    ]
    if errors:
        raise SystemExit("formal event validation failed:\n" + "\n".join(errors))
    return events


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _split_ids(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _stable_id(text: str) -> str:
    return str(sum(ord(char) for char in text) % 100000)


if __name__ == "__main__":
    raise SystemExit(main())
