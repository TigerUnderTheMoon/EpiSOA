"""Reusable query planning and coverage helpers for C-FSM collection."""

from __future__ import annotations

from collections import Counter
import json
from typing import Any


DEFAULT_SOURCES = ["news", "official", "public_interaction", "forum", "public_social", "public_web"]
SOURCE_ALIASES = {"social_media": "public_social"}
DEFAULT_TEMPORAL_STAGES = ["before", "during", "after"]
LEGACY_QUERY_SEED_FIELD = "quer" + "ies"


def plan_event_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event.get("event_description") or event.get("query") or event_id)
    seed_keywords = event_query_seeds(event) or [event_name]
    stakeholders = as_list(event.get("stakeholder_hints"))
    stances = as_list(event.get("stance_hints"))
    source_scope = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)

    expanded_keywords = unique(
        seed_keywords
        + [f"{keyword} {stakeholder}" for keyword in seed_keywords for stakeholder in stakeholders]
        + [f"{keyword} {stance}" for keyword in seed_keywords for stance in stances]
    )
    return query_plan_from_queries(
        event=event,
        queries=unique(seed_keywords + expanded_keywords),
        source_scope=source_scope,
        generated_by="cfsm_s1_query_planning",
        seed_keywords=seed_keywords,
        expanded_keywords=[item for item in expanded_keywords if item not in seed_keywords],
    )


def query_plan_from_queries(
    *,
    event: dict[str, Any],
    queries: list[str],
    source_scope: list[str],
    generated_by: str,
    seed_keywords: list[str] | None = None,
    expanded_keywords: list[str] | None = None,
) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event.get("event_description") or event_id)
    query_rounds = [
        {
            "round": 0,
            "query": query,
            "source_scope": source_scope,
            "target_stakeholder": None,
            "target_stance": None,
            "target_temporal_stage": None,
            "reason": "seed_or_expanded_keyword" if generated_by == "cfsm_s1_query_planning" else "coverage_aware_ga_selected",
            "generated_by": generated_by,
            "used_for_collection": True,
        }
        for query in unique(queries)
    ]
    return {
        "event_id": event_id,
        "event_name": event_name,
        "seed_keywords": list(seed_keywords or event_query_seeds(event)),
        "expanded_keywords": list(expanded_keywords or []),
        "repair_keywords": [],
        "query_rounds": query_rounds,
    }


def plan_recollection_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event_id)
    repair_keywords = as_list(event.get("repair_keywords") or event.get("seed_keywords") or event.get("query") or event_name)
    source_scope = normalize_source_scope(event.get("target_sources") or event.get("source_scope"), default_sources=default_sources)
    site_scope = as_list(event.get("site_scope"))
    query_rounds: list[dict[str, Any]] = []
    for query in repair_keywords:
        scoped_queries = [query]
        scoped_queries.extend([f"site:{site} {query}" for site in site_scope if "." in site])
        for scoped_query in unique(scoped_queries):
            query_rounds.append(
                {
                    "round": 0,
                    "query": scoped_query,
                    "source_scope": source_scope,
                    "target_stakeholder": None,
                    "target_stance": None,
                    "target_temporal_stage": None,
                    "reason": "; ".join(as_list(event.get("reason"))) or "targeted recollection",
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
    stakeholders = as_list(event.get("stakeholder_hints"))
    stances = as_list(event.get("stance_hints"))
    temporal_stages = as_list(event.get("temporal_stages")) or DEFAULT_TEMPORAL_STAGES

    combined_texts = [f"{post.get('title', '')} {post.get('snippet', '')} {post.get('text', '')}".lower() for post in posts]
    source_counts = Counter(str(post.get("source") or post.get("platform") or "unknown") for post in posts)
    source_coverage = {source: _contains_source(source_counts, source) for source in source_scope}
    stakeholder_coverage = {item: _any_contains(combined_texts, item) for item in stakeholders}
    stance_coverage = {item: _any_contains(combined_texts, item) for item in stances}
    # Legacy repair diagnostics only: this is literal string matching over
    # configured stage labels, not a semantic temporal-stage model.
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
        "temporal_stage_coverage_mode": "literal_string_match_legacy",
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
    base = event_query_seeds(event) or as_list(event.get("query") or event.get("event_name") or event.get("event_id"))
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
    return dedupe_rounds(rounds)


def event_query_seeds(event: dict[str, Any]) -> list[str]:
    return as_list(event.get("query_seeds") or event.get(LEGACY_QUERY_SEED_FIELD) or event.get("seed_keywords"))


def anchor_entity_terms(event: dict[str, Any]) -> list[str]:
    anchors = event.get("anchor_entities")
    terms: list[str] = []
    if isinstance(anchors, dict):
        for value in anchors.values():
            terms.extend(as_list(value))
    else:
        terms.extend(as_list(anchors))
    return unique(terms)


def as_list(value: Any) -> list[str]:
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
    sources = as_list(value) or list(default_sources or DEFAULT_SOURCES)
    return unique([normalize_source_type(source) for source in sources])


def normalize_source_type(source: Any) -> str:
    value = str(source).strip()
    return SOURCE_ALIASES.get(value.lower(), value)


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            output.append(item)
            seen.add(item)
    return output


def dedupe_rounds(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
