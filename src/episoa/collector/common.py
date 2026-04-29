"""Shared helpers and constants for the C-FSM evidence collector."""

from __future__ import annotations

from typing import Any, Literal


CoverageScenario = Literal["covered", "stakeholder_missing", "not_enough_opinions"]
CollectionMode = Literal["mock", "semireal_search"]

SUPPORTED_SEMIREAL_SOURCES = ["news", "forum", "official_response", "public_web"]
MAX_QUERIES_PER_EVENT = 8
MAX_PAGES_PER_QUERY = 5
MAX_EVIDENCE_PER_EVENT = 80
MAX_FEEDBACK_TRANSITIONS = 2
DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0
DEFAULT_USER_AGENT = "EpiSOA research crawler (+public evidence collection; contact: local researcher)"

DEFAULT_COVERAGE_WEIGHTS = {
    "relevance": 1.0,
    "stakeholder_coverage": 1.0,
    "stance_diversity": 1.0,
    "temporal_coverage": 0.7,
    "traceability": 1.0,
    "redundancy": 0.5,
    "cost": 0.2,
}


def visit(state: dict[str, Any], node_name: str) -> list[str]:
    """Append a collector FSM node to the visitation trace."""
    return [*state.get("visited_states", []), node_name]


def collection_mode(state: dict[str, Any]) -> CollectionMode:
    """Return the active collection mode, defaulting to mock."""
    return "semireal_search" if state.get("collection_mode") == "semireal_search" else "mock"


def bounded_int(state: dict[str, Any], key: str, default: int, upper_bound: int) -> int:
    """Read an integer config value with a hard upper bound."""
    try:
        value = int(state.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, upper_bound))


def source_type_for_evidence(source: str) -> str:
    """Map collector source families to EvidenceRecord source_type values."""
    if source == "official_response":
        return "official"
    if source in {"news", "forum", "blog", "other"}:
        return source
    return "other"


def coverage_weights(state: dict[str, Any]) -> dict[str, float]:
    """Return configured coverage objective weights with stable defaults."""
    raw = state.get("coverage_weights", {})
    weights = dict(DEFAULT_COVERAGE_WEIGHTS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in weights:
                try:
                    weights[key] = float(value)
                except (TypeError, ValueError):
                    continue
    return weights
