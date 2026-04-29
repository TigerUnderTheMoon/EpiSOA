"""S1 query planning for C-FSM evidence collection."""

from __future__ import annotations

from typing import Any

from episoa.collector.common import MAX_QUERIES_PER_EVENT, bounded_int, collection_mode, visit


def query_planning(state: dict[str, Any]) -> dict[str, Any]:
    """Plan bounded queries covering stakeholders, source scope, and time stages."""
    target_event = state.get("target_event", "event")
    existing_plan = list(state.get("query_plan", []))
    if collection_mode(state) == "semireal_search":
        max_queries = bounded_int(state, "max_queries_per_event", MAX_QUERIES_PER_EVENT, MAX_QUERIES_PER_EVENT)
        stakeholders = [str(value).strip() for value in state.get("stakeholders", []) if str(value).strip()]
        source_scope = [str(value).strip() for value in state.get("source_scope", []) if str(value).strip()]
        time_stages = [str(value).strip() for value in state.get("time_stages", []) if str(value).strip()]
        source_terms = source_scope or ["news", "forum", "official response", "public web"]
        queries = list(existing_plan)
        candidates = [
            target_event,
            f"{target_event} public comments",
            f"{target_event} stakeholder reaction",
            f"{target_event} official response",
            f"{target_event} forum discussion",
            *[f"{target_event} {stakeholder} opinion" for stakeholder in stakeholders],
            *[f"{target_event} {source_term}" for source_term in source_terms],
            *[f"{target_event} {stage} reactions" for stage in time_stages],
        ]
        if state.get("coverage_status", {}).get("stakeholder_coverage") == "stakeholder_missing":
            candidates.insert(1, f"{target_event} missing stakeholder response")
        for query in candidates:
            query = " ".join(str(query).split())
            if query and query not in queries:
                queries.append(query)
            if len(queries) >= max_queries:
                break
        return {
            "visited_states": visit(state, "query_planning"),
            "query_plan": queries[:max_queries],
        }

    repair_query = f"{target_event} stakeholder reactions"
    query_plan = existing_plan or [f"{target_event} timeline", f"{target_event} public opinion"]
    if repair_query not in query_plan:
        query_plan = [*query_plan, repair_query]

    return {
        "visited_states": visit(state, "query_planning"),
        "query_plan": query_plan,
    }
