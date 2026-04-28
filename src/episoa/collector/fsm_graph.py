"""FSM-style agentic evidence collector built with LangGraph."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from episoa.preprocess.privacy_filter import clean_raw_evidence
from episoa.schemas.evidence import EvidenceRecord


CoverageScenario = Literal["covered", "stakeholder_missing", "not_enough_opinions"]
CollectionMode = Literal["mock", "semireal_search"]
SUPPORTED_SEMIREAL_SOURCES = ["news", "forum", "official_response", "public_web"]
MAX_QUERIES_PER_EVENT = 8
MAX_PAGES_PER_QUERY = 5
MAX_EVIDENCE_PER_EVENT = 80
MAX_FEEDBACK_TRANSITIONS = 2


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
    max_queries_per_event: int
    max_pages_per_query: int
    max_evidence_per_event: int


def _visit(state: CollectorState, node_name: str) -> list[str]:
    return [*state.get("visited_states", []), node_name]


def _collection_mode(state: CollectorState) -> CollectionMode:
    return "semireal_search" if state.get("collection_mode") == "semireal_search" else "mock"


def _limit(state: CollectorState, key: str, default: int, upper_bound: int) -> int:
    try:
        value = int(state.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, upper_bound))


def _source_type_for_evidence(source: str) -> str:
    return "official" if source == "official_response" else source if source in {"news", "forum", "blog", "other"} else "other"


def event_understanding(state: CollectorState) -> CollectorState:
    """Understand the target event for downstream query planning."""
    target_event = state.get("target_event", "unknown event")
    if _collection_mode(state) == "semireal_search":
        time_window = state.get("time_window", {})
        window_text = ""
        if time_window:
            window_text = f" during {time_window.get('start', '?')} to {time_window.get('end', '?')}"
        return {
            "visited_states": _visit(state, "event_understanding"),
            "event_summary": f"Semi-real collection target: {target_event}{window_text}",
            "max_coverage_attempts": MAX_FEEDBACK_TRANSITIONS + 1,
        }
    return {
        "visited_states": _visit(state, "event_understanding"),
        "event_summary": f"Mock understanding for {target_event}",
    }


def query_planning(state: CollectorState) -> CollectorState:
    """Plan bounded public-web search queries."""
    target_event = state.get("target_event", "event")
    existing_plan = state.get("query_plan", [])
    if _collection_mode(state) == "semireal_search":
        max_queries = _limit(state, "max_queries_per_event", MAX_QUERIES_PER_EVENT, MAX_QUERIES_PER_EVENT)
        stakeholders = [str(value) for value in state.get("stakeholders", []) if str(value).strip()]
        source_terms = ["news", "forum", "official response", "public web"]
        queries = list(existing_plan)
        candidates = [
            target_event,
            f"{target_event} public comments",
            f"{target_event} stakeholder reaction",
            f"{target_event} official response",
            f"{target_event} forum discussion",
            *[f"{target_event} {stakeholder} opinion" for stakeholder in stakeholders],
            *[f"{target_event} {source_term}" for source_term in source_terms],
        ]
        if state.get("coverage_status", {}).get("stakeholder_coverage") == "stakeholder_missing":
            candidates.insert(1, f"{target_event} missing stakeholder response")
        for query in candidates:
            query = " ".join(query.split())
            if query and query not in queries:
                queries.append(query)
            if len(queries) >= max_queries:
                break
        return {
            "visited_states": _visit(state, "query_planning"),
            "query_plan": queries[:max_queries],
        }

    repair_query = f"{target_event} stakeholder reactions"
    query_plan = existing_plan or [f"{target_event} timeline", f"{target_event} public opinion"]
    if repair_query not in query_plan:
        query_plan = [*query_plan, repair_query]

    return {
        "visited_states": _visit(state, "query_planning"),
        "query_plan": query_plan,
    }


def source_selection(state: CollectorState) -> CollectorState:
    """Select source families for public evidence collection."""
    if _collection_mode(state) == "semireal_search":
        requested = [str(item) for item in state.get("source_types", [])]
        selected = [item for item in requested if item in SUPPORTED_SEMIREAL_SOURCES]
        if not selected:
            selected = list(SUPPORTED_SEMIREAL_SOURCES)
        return {
            "visited_states": _visit(state, "source_selection"),
            "selected_sources": selected,
        }
    return {
        "visited_states": _visit(state, "source_selection"),
        "selected_sources": ["news", "social_media", "official"],
    }


def search_and_page_collection(state: CollectorState) -> CollectorState:
    """Collect bounded page records from mock data, search results, or seed URLs."""
    if _collection_mode(state) == "semireal_search":
        max_pages = _limit(state, "max_pages_per_query", MAX_PAGES_PER_QUERY, MAX_PAGES_PER_QUERY)
        max_evidence = _limit(state, "max_evidence_per_event", MAX_EVIDENCE_PER_EVENT, MAX_EVIDENCE_PER_EVENT)
        selected_sources = set(state.get("selected_sources", SUPPORTED_SEMIREAL_SOURCES))
        search_results = state.get("search_results", {})
        pages: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for query in state.get("query_plan", [])[:MAX_QUERIES_PER_EVENT]:
            query_pages = list(search_results.get(query, []))[:max_pages]
            if not query_pages and state.get("seed_urls"):
                query_pages = [_seed_to_page(seed, query) for seed in state.get("seed_urls", [])][:max_pages]
            for page in query_pages:
                source = str(page.get("source") or page.get("source_type") or "public_web")
                if source not in selected_sources:
                    continue
                url = str(page.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                pages.append({**page, "query": query, "source": source})
                if len(pages) >= max_evidence:
                    break
            if len(pages) >= max_evidence:
                break

        return {
            "visited_states": _visit(state, "search_and_page_collection"),
            "pages": pages,
        }

    pages = [
        {
            "url": "https://example.com/news/mock-event",
            "title": "Mock event coverage",
            "source": "news",
        },
        {
            "url": "https://example.com/social/mock-event",
            "title": "Mock public reactions",
            "source": "social_media",
        },
    ]
    return {
        "visited_states": _visit(state, "search_and_page_collection"),
        "pages": pages,
    }


def browser_based_opinion_collection(state: CollectorState) -> CollectorState:
    """Extract opinion-like snippets without opening a real browser in tests."""
    if _collection_mode(state) == "semireal_search":
        opinions: list[dict[str, Any]] = []
        for index, page in enumerate(state.get("pages", []), start=1):
            text = str(page.get("text") or page.get("snippet") or page.get("title") or "")
            if not text:
                continue
            metadata = dict(page.get("metadata") or {})
            opinions.append(
                {
                    "evidence_id": page.get("evidence_id", f"semireal-{index:03d}"),
                    "platform": page.get("platform") or page.get("source") or "public_web",
                    "url": page.get("url"),
                    "timestamp": page.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                    "text": text,
                    "author_name": page.get("author_name"),
                    "author_username": page.get("author_username"),
                    "author_profile_url": page.get("author_profile_url"),
                    "source_type": _source_type_for_evidence(str(page.get("source") or "public_web")),
                    "metadata": {
                        **metadata,
                        "stakeholder": metadata.get("stakeholder", page.get("stakeholder", "unknown")),
                        "stance": metadata.get("stance", page.get("stance", metadata.get("sentiment", "unknown"))),
                        "sentiment": metadata.get("sentiment", page.get("sentiment", "unknown")),
                        "event": metadata.get("event", state.get("target_event", "unknown event")),
                        "query": page.get("query"),
                        "source_family": page.get("source", "public_web"),
                    },
                }
            )
        return {
            "visited_states": _visit(state, "browser_based_opinion_collection"),
            "opinions": opinions,
        }

    return {
        "visited_states": _visit(state, "browser_based_opinion_collection"),
        "opinions": [
            {
                "stakeholder": "customers",
                "stance": "supportive",
                "text": "The change seems necessary.",
            },
            {
                "stakeholder": "employees",
                "stance": "concerned",
                "text": "The timeline may be difficult.",
            },
        ],
    }


def evidence_normalization(state: CollectorState) -> CollectorState:
    """Normalize evidence and apply privacy filtering in semi-real mode."""
    if _collection_mode(state) == "semireal_search":
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
            "visited_states": _visit(state, "evidence_normalization"),
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
        "visited_states": _visit(state, "evidence_normalization"),
        "evidence": evidence,
    }


def _mock_coverage_status(scenario: CoverageScenario) -> CoverageStatus:
    if scenario == "stakeholder_missing":
        return {
            "stakeholder_coverage": "stakeholder_missing",
            "stance_diversity": "sufficient",
            "temporal_coverage": "sufficient",
            "traceability_rate": 0.9,
            "redundancy_rate": 0.2,
        }
    if scenario == "not_enough_opinions":
        return {
            "stakeholder_coverage": "sufficient",
            "stance_diversity": "not_enough_opinions",
            "temporal_coverage": "sufficient",
            "traceability_rate": 0.8,
            "redundancy_rate": 0.2,
        }
    return {
        "stakeholder_coverage": "sufficient",
        "stance_diversity": "sufficient",
        "temporal_coverage": "sufficient",
        "traceability_rate": 0.95,
        "redundancy_rate": 0.15,
    }


def coverage_evaluation(state: CollectorState) -> CollectorState:
    """Evaluate coverage and decide whether feedback transitions are needed.

    The first coverage attempt can be forced with ``mock_coverage_scenario``.
    After one remediation loop the mock returns a passing status, keeping tests
    finite while still exercising conditional FSM edges.
    """
    attempts = state.get("coverage_attempts", 0) + 1
    max_attempts = int(state.get("max_coverage_attempts", MAX_FEEDBACK_TRANSITIONS + 1))
    if _collection_mode(state) == "semireal_search":
        status = _semireal_coverage_status(state)
    else:
        scenario = state.get("mock_coverage_scenario", "covered")
        status = _mock_coverage_status(scenario if attempts == 1 else "covered")

    if attempts >= max_attempts and (
        status.get("stakeholder_coverage") != "sufficient"
        or status.get("stance_diversity") != "sufficient"
    ):
        status = {
            "stakeholder_coverage": "failed",
            "stance_diversity": "failed",
            "temporal_coverage": status.get("temporal_coverage", "failed"),
            "traceability_rate": float(status.get("traceability_rate", 0.0)),
            "redundancy_rate": float(status.get("redundancy_rate", 1.0)),
        }

    return {
        "visited_states": _visit(state, "coverage_evaluation"),
        "coverage_attempts": attempts,
        "coverage_status": status,
    }


def stop_and_handoff(state: CollectorState) -> CollectorState:
    """Final mock handoff node."""
    return {
        "visited_states": _visit(state, "stop_and_handoff"),
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


def _seed_to_page(seed: str | dict[str, Any], query: str) -> dict[str, Any]:
    if isinstance(seed, dict):
        return {**seed, "query": query}
    return {
        "url": str(seed),
        "title": str(seed),
        "text": f"Public seed page related to {query}",
        "platform": "public_web",
        "source": "public_web",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"stakeholder": "unknown", "sentiment": "unknown"},
    }


def _semireal_coverage_status(state: CollectorState) -> CoverageStatus:
    evidence = list(state.get("evidence", []))
    if not evidence:
        return {
            "stakeholder_coverage": "stakeholder_missing",
            "stance_diversity": "not_enough_opinions",
            "temporal_coverage": "insufficient",
            "traceability_rate": 0.0,
            "redundancy_rate": 0.0,
        }

    stakeholders = {
        str(item.get("metadata", {}).get("stakeholder", "unknown")).strip().lower()
        for item in evidence
    }
    stakeholders.discard("")
    stakeholders.discard("unknown")
    stances = {
        str(
            item.get("metadata", {}).get("stance")
            or item.get("metadata", {}).get("sentiment")
            or "unknown"
        ).strip().lower()
        for item in evidence
    }
    stances.discard("")
    stances.discard("unknown")
    timestamps = [item.get("timestamp") for item in evidence if item.get("timestamp")]
    traceable = [item for item in evidence if item.get("url") and item.get("evidence_id")]
    texts = [" ".join(str(item.get("text", "")).lower().split()) for item in evidence]
    duplicate_count = sum(count - 1 for count in Counter(texts).values() if count > 1)

    stakeholder_status = "sufficient" if len(stakeholders) >= 2 else "stakeholder_missing"
    stance_status = "sufficient" if len(stances) >= 2 else "not_enough_opinions"
    temporal_status = "sufficient" if len(set(timestamps)) >= 2 or len(evidence) == 1 else "insufficient"
    traceability_rate = len(traceable) / len(evidence)
    redundancy_rate = duplicate_count / len(evidence)

    if traceability_rate < 0.8:
        stakeholder_status = "stakeholder_missing"
    if redundancy_rate > 0.6:
        stance_status = "not_enough_opinions"

    return {
        "stakeholder_coverage": stakeholder_status,
        "stance_diversity": stance_status,
        "temporal_coverage": temporal_status,
        "traceability_rate": round(traceability_rate, 4),
        "redundancy_rate": round(redundancy_rate, 4),
    }


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
