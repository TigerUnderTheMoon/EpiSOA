"""Reusable query planning and coverage helpers for C-FSM collection."""

from __future__ import annotations

from collections import Counter
import json
from typing import Any

from episoa.collector.coverage_extractor import evaluate_event_coverage, load_source_detection_config


DEFAULT_SOURCES = ["news", "official", "public_interaction", "forum", "public_social", "public_web"]
SOURCE_ALIASES = {"social_media": "public_social"}
DEFAULT_TEMPORAL_STAGES = ["before", "during", "after"]
LEGACY_QUERY_SEED_FIELD = "quer" + "ies"
SOURCE_QUERY_TEMPLATES = {
    "official": ["{seed} 官方 回应"],
    "news": ["{seed}"],
    "public_interaction": ["{seed} 投诉 留言"],
    "forum": ["{seed} 论坛 业主"],
    "public_social": ["{seed} 微博 网友"],
    "public_web": ["{seed}"],
}
STAKEHOLDER_TERMS = ["政府", "居民", "开发商", "企业", "媒体", "专家"]
STANCE_TERMS = ["支持", "反对", "质疑", "投诉", "争议", "回应"]
TEMPORAL_STAGE_TERMS = ["规划", "公示", "实施", "争议", "回应", "整改", "结果"]
STANCE_REPAIR_TERMS = ["居民 反映", "投诉 回应", "质疑 部门回应", "业主 维权", "整改 回复", "争议 通报"]
TEMPORAL_REPAIR_TERMS = ["公示", "施工", "投诉", "回应", "整改", "办结", "后续"]
LOW_RAW_REPAIR_TERMS = ["进展", "公告", "回应", "投诉", "整改", "新闻"]
SEMANTIC_REPAIR_BUDGET = 6
TEMPORAL_REPAIR_BUDGET = 7
LOW_RAW_REPAIR_BUDGET = 6
LOW_RAW_SOURCE_PRIORITY = ["news", "official", "public_interaction"]


def plan_event_queries(event: dict[str, Any], default_sources: list[str] | None = None) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event.get("event_description") or event.get("query") or event_id)
    seed_keywords = event_query_seeds(event) or [event_name]
    stakeholders = as_list(event.get("stakeholder_hints"))
    stances = as_list(event.get("stance_hints"))
    source_scope = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    stakeholder_terms = unique(stakeholders[:2] + STAKEHOLDER_TERMS[:2])
    stance_terms = unique(stances[:2] + STANCE_TERMS[:2])
    temporal_terms = unique(as_list(event.get("temporal_stages"))[:2] + TEMPORAL_STAGE_TERMS[:2])
    expanded_keywords = unique(seed_keywords + stakeholder_terms + stance_terms + temporal_terms)
    return query_plan_from_queries(
        event=event,
        queries=unique(seed_keywords),
        source_scope=source_scope,
        generated_by="cfsm_s1_query_planning",
        seed_keywords=seed_keywords,
        expanded_keywords=[item for item in expanded_keywords if item not in seed_keywords],
        stakeholder_terms=stakeholder_terms,
        stance_terms=stance_terms,
        temporal_terms=temporal_terms,
    )


def query_plan_from_queries(
    *,
    event: dict[str, Any],
    queries: list[str],
    source_scope: list[str],
    generated_by: str,
    seed_keywords: list[str] | None = None,
    expanded_keywords: list[str] | None = None,
    stakeholder_terms: list[str] | None = None,
    stance_terms: list[str] | None = None,
    temporal_terms: list[str] | None = None,
) -> dict[str, Any]:
    event_id = str(event.get("event_id", "")).strip()
    event_name = str(event.get("event_name") or event.get("event_description") or event_id)
    query_rounds: list[dict[str, Any]] = []
    query_list = unique(queries)
    for source in source_scope:
        if source == "official":
            for item in _official_query_items(event, query_list, phase="first_pass"):
                query_rounds.append(
                    _query_round(
                        round_index=0,
                        query=item["query"],
                        source=source,
                        generated_by=generated_by,
                        reason="official_source_template"
                        if generated_by == "cfsm_s1_query_planning"
                        else "coverage_aware_ga_selected",
                        query_template=item["query_template"],
                    )
                )
            continue
        for query in query_list:
            for templated_query in _source_queries(query, source):
                query_rounds.append(
                    _query_round(
                        round_index=0,
                        query=templated_query,
                        source=source,
                        generated_by=generated_by,
                        reason="seed_source_template"
                        if generated_by == "cfsm_s1_query_planning"
                        else "coverage_aware_ga_selected",
                    )
                )
    semantic_source = next((source for source in source_scope if source != "official"), source_scope[0])
    for query in unique(queries)[:2]:
        for stakeholder in unique(stakeholder_terms or [])[:2]:
            query_rounds.append(
                _query_round(
                    round_index=0,
                    query=f"{query} {stakeholder}",
                    source=semantic_source,
                    generated_by=generated_by,
                    reason=f"stakeholder coverage seed: {stakeholder}",
                    target_stakeholder=stakeholder,
                )
            )
        for stance in unique(stance_terms or [])[:2]:
            query_rounds.append(
                _query_round(
                    round_index=0,
                    query=f"{query} {stance}",
                    source=semantic_source,
                    generated_by=generated_by,
                    reason=f"stance coverage seed: {stance}",
                    target_stance=stance,
                )
            )
        for stage in unique(temporal_terms or [])[:2]:
            query_rounds.append(
                _query_round(
                    round_index=0,
                    query=f"{query} {stage}",
                    source=semantic_source,
                    generated_by=generated_by,
                    reason=f"temporal coverage seed: {stage}",
                    target_temporal_stage=stage,
                )
            )
    query_rounds = dedupe_rounds(query_rounds)
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
    return evaluate_event_coverage(event, posts, default_sources=default_sources)


def build_repair_rounds(
    event: dict[str, Any], coverage: dict[str, Any], repair_round: int, default_sources: list[str] | None = None
) -> list[dict[str, Any]]:
    base = event_query_seeds(event) or as_list(event.get("query") or event.get("event_name") or event.get("event_id"))
    event_sources = normalize_source_scope(event.get("source_scope"), default_sources=default_sources)
    repair_targets: list[tuple[str, str | None, str | None, str | None, str]] = []
    if "official" in coverage["missing_sources"]:
        return [
            _query_round(
                round_index=repair_round,
                query=item["query"],
                source="official",
                generated_by="cfsm_s6_query_repair",
                reason="missing_official",
                query_template=item["query_template"],
            )
            for item in _official_query_items(event, base, phase="repair")
        ]
    for source in coverage["missing_sources"]:
        repair_targets.append((source, None, None, None, f"missing source: {source}"))
    if not coverage["missing_sources"]:
        for stakeholder in coverage["missing_stakeholders"][:1]:
            repair_targets.append((event_sources[0], stakeholder, None, None, f"missing stakeholder: {stakeholder}"))
        if coverage["missing_stances"]:
            repair_targets.extend(
                _semantic_repair_targets(
                    event_sources=event_sources,
                    terms=STANCE_REPAIR_TERMS,
                    budget=SEMANTIC_REPAIR_BUDGET,
                    reason="missing stance",
                    target_field="stance",
                )
            )
        if coverage["missing_temporal_stages"]:
            repair_targets.extend(
                _semantic_repair_targets(
                    event_sources=event_sources,
                    terms=TEMPORAL_REPAIR_TERMS,
                    budget=TEMPORAL_REPAIR_BUDGET,
                    reason="missing temporal stage",
                    target_field="temporal",
                )
            )
    if coverage.get("missing_raw_count"):
        return _low_raw_repair_rounds(base, event_sources, repair_round)
    if repair_targets and any(reason in {"missing stance", "missing temporal stage"} for *_, reason in repair_targets):
        rounds = []
        for keyword in base:
            for source, stakeholder, stance, stage, reason in repair_targets:
                query = " ".join([str(part) for part in [keyword, stakeholder, stance, stage] if part])
                for templated_query in _source_queries(query, source):
                    rounds.append(
                        _query_round(
                            round_index=repair_round,
                            query=templated_query,
                            source=source,
                            generated_by="cfsm_s6_query_repair",
                            reason=reason,
                            target_stakeholder=stakeholder,
                            target_stance=stance,
                            target_temporal_stage=stage,
                        )
                    )
        return dedupe_rounds(rounds)[: SEMANTIC_REPAIR_BUDGET + TEMPORAL_REPAIR_BUDGET]
    if not repair_targets:
        for source in event_sources[:5]:
            repair_targets.append((source, None, None, None, "no posts collected"))

    rounds: list[dict[str, Any]] = []
    for keyword in base:
        for source, stakeholder, stance, stage, reason in repair_targets:
            parts = [keyword, stakeholder, stance, stage]
            query = " ".join([str(part) for part in parts if part])
            for templated_query in _source_queries(query, source):
                rounds.append(
                    _query_round(
                        round_index=repair_round,
                        query=templated_query,
                        source=source,
                        generated_by="cfsm_s6_query_repair",
                        reason=reason,
                        target_stakeholder=stakeholder,
                        target_stance=stance,
                        target_temporal_stage=stage,
                    )
                )
    return dedupe_rounds(rounds)


def _semantic_repair_targets(
    *,
    event_sources: list[str],
    terms: list[str],
    budget: int,
    reason: str,
    target_field: str,
) -> list[tuple[str, str | None, str | None, str | None, str]]:
    source = _first_available_source(event_sources, ["public_interaction", "news", "forum", "public_social", "public_web"])
    rows: list[tuple[str, str | None, str | None, str | None, str]] = []
    for term in terms[:budget]:
        if target_field == "stance":
            rows.append((source, None, term, None, reason))
        else:
            rows.append((source, None, None, term, reason))
    return rows


def _low_raw_repair_rounds(base: list[str], event_sources: list[str], repair_round: int) -> list[dict[str, Any]]:
    sources = [source for source in LOW_RAW_SOURCE_PRIORITY if source in event_sources] or event_sources[:3]
    rounds: list[dict[str, Any]] = []
    for keyword in base:
        for source in sources:
            for term in LOW_RAW_REPAIR_TERMS:
                query = " ".join([keyword, term])
                for templated_query in _source_queries(query, source):
                    rounds.append(
                        _query_round(
                            round_index=repair_round,
                            query=templated_query,
                            source=source,
                            generated_by="cfsm_s6_query_repair",
                            reason="raw count below minimum",
                        )
                    )
                if len(dedupe_rounds(rounds)) >= LOW_RAW_REPAIR_BUDGET:
                    return dedupe_rounds(rounds)[:LOW_RAW_REPAIR_BUDGET]
    return dedupe_rounds(rounds)[:LOW_RAW_REPAIR_BUDGET]


def _first_available_source(event_sources: list[str], preferred: list[str]) -> str:
    for source in preferred:
        if source in event_sources:
            return source
    return event_sources[0] if event_sources else "news"


def _source_queries(seed: str, source: str) -> list[str]:
    templates = SOURCE_QUERY_TEMPLATES.get(source, ["{seed}"])
    return unique([template.format(seed=seed) for template in templates])


def _official_query_items(event: dict[str, Any], seeds: list[str], *, phase: str) -> list[dict[str, str]]:
    config = load_source_detection_config()
    templates = list((config.get("official_query_templates") or {}).get(phase) or [])
    if not templates:
        templates = ["site:gov.cn {seed}", "site:gov.cn {seed} 公示 公告", "{department} {project} 公示 公告 批复"]
    budget_key = "official_repair_budget" if phase == "repair" else "official_first_pass_budget"
    budget = int(config.get(budget_key) or (8 if phase == "repair" else 4))
    context = _official_query_context(event, seeds)
    rows: list[dict[str, str]] = []
    for template in templates:
        departments = context["departments"] if "{department}" in template else [""]
        local_domains = context["local_gov_domains"] if "{local_gov_domain}" in template else [""]
        for local_gov_domain in local_domains:
            for department in departments:
                values = dict(context)
                values["department"] = department
                values["local_gov_domain"] = local_gov_domain
                query = " ".join(template.format(**values).split())
                if query and "site: " not in query:
                    rows.append({"query": query, "query_template": template})
                if len(unique([row["query"] for row in rows])) >= budget:
                    return _dedupe_query_items(rows)[:budget]
    return _dedupe_query_items(rows)[:budget]


def _official_query_context(event: dict[str, Any], seeds: list[str]) -> dict[str, Any]:
    location_terms = _location_terms(event)
    project = _project_term(event, seeds)
    location = " ".join(location_terms[:2]) or project
    seed = seeds[0] if seeds else project
    config = load_source_detection_config()
    local_domains = _local_gov_domains(location_terms, config)
    departments = unique(
        [
            *[term for term in location_terms if any(keyword in term for keyword in ("政府", "街道", "住建", "自然资源"))],
            *as_list(config.get("official_department_keywords"))[:6],
        ]
    )
    return {
        "seed": seed,
        "project": project,
        "location": location,
        "departments": departments or ["自然资源局", "住房和城乡建设局", "街道办"],
        "local_gov_domains": local_domains or ["gov.cn"],
    }


def _local_gov_domains(location_terms: list[str], config: dict[str, Any]) -> list[str]:
    mapping = config.get("local_gov_domains") or {}
    domains: list[str] = []
    if isinstance(mapping, dict):
        for term in reversed(location_terms):
            domains.extend(as_list(mapping.get(term)))
    return unique(domains)[:1]


def _location_terms(event: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    location = event.get("location")
    if isinstance(location, dict):
        terms.extend(as_list(location.get("city")))
        terms.extend(as_list(location.get("district")))
        terms.extend(as_list(location.get("county")))
    else:
        terms.extend(as_list(location))
    terms.extend(anchor_entity_terms(event))
    return unique(terms)


def _project_term(event: dict[str, Any], seeds: list[str]) -> str:
    for seed in seeds:
        if seed:
            return seed
    return str(event.get("event_name") or event.get("event_description") or event.get("event_id") or "").strip()


def _dedupe_query_items(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        query = row["query"]
        if query not in seen:
            output.append(row)
            seen.add(query)
    return output


def _query_round(
    *,
    round_index: int,
    query: str,
    source: str,
    generated_by: str,
    reason: str,
    target_stakeholder: str | None = None,
    target_stance: str | None = None,
    target_temporal_stage: str | None = None,
    query_template: str | None = None,
) -> dict[str, Any]:
    source = normalize_source_type(source)
    row = {
        "round": round_index,
        "query": query,
        "source_type": source,
        "source_scope": [source],
        "target_stakeholder": target_stakeholder,
        "target_stance": target_stance,
        "target_temporal_stage": target_temporal_stage,
        "reason": reason,
        "generated_by": generated_by,
        "used_for_collection": True,
    }
    if query_template:
        row["query_template"] = query_template
    return row


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
    seen: set[tuple[str, int, str]] = set()
    output: list[dict[str, Any]] = []
    for item in rounds:
        source = str(item.get("source_type") or ",".join(normalize_source_scope(item.get("source_scope"))))
        key = (str(item["query"]), int(item["round"]), source)
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
