"""FSM-style agentic evidence collector built with LangGraph."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from episoa.collector.common import (
    MAX_EVIDENCE_PER_EVENT,
    CollectionMode,
    CoverageScenario,
    collection_mode,
    visit,
)
from episoa.collector.coverage_evaluation import coverage_evaluation
from episoa.collector.event_understanding import event_understanding
from episoa.collector.opinion_collection import browser_based_opinion_collection
from episoa.collector.page_collection import search_and_page_collection
from episoa.collector.query_planning import query_planning
from episoa.collector.source_selection import source_selection
from episoa.preprocess.privacy_filter import clean_raw_evidence
from episoa.schemas.evidence import EvidenceRecord


class CoverageStatus(TypedDict):
    """Coverage metrics used to decide whether collection should continue."""

    stakeholder_coverage: str
    stance_diversity: str
    temporal_coverage: str
    traceability_rate: float
    redundancy_rate: float


class CollectorState(TypedDict, total=False):
    """Mutable state passed between evidence collector FSM nodes."""

    target_event: str
    event_summary: str
    query_plan: list[str]
    selected_sources: list[str]
    pages: list[dict[str, Any]]
    opinions: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    coverage_status: CoverageStatus
    handoff_payload: dict[str, Any]
    visited_states: list[str]
    coverage_attempts: int
    max_coverage_attempts: int
    mock_coverage_scenario: CoverageScenario
    collection_mode: CollectionMode
    time_window: dict[str, Any]
    seed_urls: list[str | dict[str, Any]]
    search_results: dict[str, list[dict[str, Any]]]
    source_types: list[str]
    source_scope: list[str]
    time_stages: list[str]
    fetch_seed_urls: bool
    fetch_search_results: bool
    http_timeout_seconds: float
    user_agent: str
    page_fetcher: Any
    fetch_errors: list[str]
    coverage_weights: dict[str, float]
    min_stakeholders: int
    min_stances: int
    min_time_stages: int
    min_traceability_rate: float
    max_redundancy_rate: float
    max_queries_per_event: int
    max_pages_per_query: int
    max_evidence_per_event: int


def _limit(state: CollectorState, key: str, default: int, upper_bound: int) -> int:
    try:
        value = int(state.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, upper_bound))


def evidence_normalization(state: CollectorState) -> CollectorState:
    """Normalize evidence and apply privacy filtering in semi-real mode."""
    if collection_mode(state) == "semireal_search":
        max_evidence = _limit(state, "max_evidence_per_event", MAX_EVIDENCE_PER_EVENT, MAX_EVIDENCE_PER_EVENT)
        evidence: list[dict[str, Any]] = []
        for opinion in state.get("opinions", [])[:max_evidence]:
            try:
                cleaned = clean_raw_evidence(dict(opinion))
                record = EvidenceRecord.model_validate(cleaned)
            except Exception:
                continue
            evidence.append(record.model_dump(mode="json"))
        return {
            "visited_states": visit(state, "evidence_normalization"),
            "evidence": evidence[:max_evidence],
        }

    evidence = [
        {
            "evidence_id": "mock-001",
            "platform": "example",
            "url": "https://example.com/news/mock-event",
            "text": "Mock evidence item.",
            "source_type": "news",
        }
    ]
    return {
        "visited_states": visit(state, "evidence_normalization"),
        "evidence": evidence,
    }


def stop_and_handoff(state: CollectorState) -> CollectorState:
    """Final mock handoff node."""
    return {
        "visited_states": visit(state, "stop_and_handoff"),
        "handoff_payload": {
            "target_event": state.get("target_event"),
            "evidence": state.get("evidence", []),
            "coverage_status": state.get("coverage_status"),
        },
    }


def route_after_coverage(state: CollectorState) -> str:
    """Choose the next FSM state from coverage metrics."""
    coverage_status = state.get("coverage_status", {})
    attempts = int(state.get("coverage_attempts", 0))
    max_attempts = int(state.get("max_coverage_attempts", 3))

    if attempts >= max_attempts:
        return "stop_and_handoff"

    if coverage_status.get("stakeholder_coverage") == "stakeholder_missing":
        return "query_planning"
    if coverage_status.get("stance_diversity") == "not_enough_opinions":
        return "search_and_page_collection"
    return "stop_and_handoff"


def build_collector_graph():
    """Build and compile the FSM-style evidence collector graph."""
    graph = StateGraph(CollectorState)

    graph.add_node("event_understanding", event_understanding)
    graph.add_node("query_planning", query_planning)
    graph.add_node("source_selection", source_selection)
    graph.add_node("search_and_page_collection", search_and_page_collection)
    graph.add_node("browser_based_opinion_collection", browser_based_opinion_collection)
    graph.add_node("evidence_normalization", evidence_normalization)
    graph.add_node("coverage_evaluation", coverage_evaluation)
    graph.add_node("stop_and_handoff", stop_and_handoff)

    graph.add_edge(START, "event_understanding")
    graph.add_edge("event_understanding", "query_planning")
    graph.add_edge("query_planning", "source_selection")
    graph.add_edge("source_selection", "search_and_page_collection")
    graph.add_edge("search_and_page_collection", "browser_based_opinion_collection")
    graph.add_edge("browser_based_opinion_collection", "evidence_normalization")
    graph.add_edge("evidence_normalization", "coverage_evaluation")
    graph.add_conditional_edges(
        "coverage_evaluation",
        route_after_coverage,
        {
            "query_planning": "query_planning",
            "search_and_page_collection": "search_and_page_collection",
            "stop_and_handoff": "stop_and_handoff",
        },
    )
    graph.add_edge("stop_and_handoff", END)

    return graph.compile()


collector_graph = build_collector_graph()
