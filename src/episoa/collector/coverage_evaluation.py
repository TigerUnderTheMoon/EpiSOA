"""S6 coverage evaluation for C-FSM evidence collection."""

from __future__ import annotations

from collections import Counter
from typing import Any

from episoa.collector.common import (
    DEFAULT_COVERAGE_WEIGHTS,
    MAX_FEEDBACK_TRANSITIONS,
    collection_mode,
    coverage_weights,
    visit,
)


def coverage_evaluation(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate coverage and decide whether feedback transitions are needed."""
    attempts = state.get("coverage_attempts", 0) + 1
    max_attempts = int(state.get("max_coverage_attempts", MAX_FEEDBACK_TRANSITIONS + 1))
    if collection_mode(state) == "semireal_search":
        status = semireal_coverage_status(state)
    else:
        scenario = state.get("mock_coverage_scenario", "covered")
        status = mock_coverage_status(scenario if attempts == 1 else "covered")

    objective = coverage_objective(status, state)
    status = {**status, "coverage_objective": round(objective, 4), "coverage_weights": coverage_weights(state)}
    if attempts >= max_attempts and (
        status.get("stakeholder_coverage") != "sufficient"
        or status.get("stance_diversity") != "sufficient"
    ):
        status = {
            **status,
            "stakeholder_coverage": "failed",
            "stance_diversity": "failed",
            "temporal_coverage": status.get("temporal_coverage", "failed"),
            "traceability_rate": float(status.get("traceability_rate", 0.0)),
            "redundancy_rate": float(status.get("redundancy_rate", 1.0)),
        }

    return {
        "visited_states": visit(state, "coverage_evaluation"),
        "coverage_attempts": attempts,
        "coverage_status": status,
    }


def mock_coverage_status(scenario: str) -> dict[str, Any]:
    """Return deterministic mock coverage states for tests and smoke runs."""
    if scenario == "stakeholder_missing":
        return {
            "stakeholder_coverage": "stakeholder_missing",
            "stakeholder_coverage_rate": 0.4,
            "stance_diversity": "sufficient",
            "stance_diversity_rate": 1.0,
            "temporal_coverage": "sufficient",
            "temporal_coverage_rate": 1.0,
            "traceability_rate": 0.9,
            "redundancy_rate": 0.2,
            "relevance": 0.8,
            "cost": 0.1,
        }
    if scenario == "not_enough_opinions":
        return {
            "stakeholder_coverage": "sufficient",
            "stakeholder_coverage_rate": 1.0,
            "stance_diversity": "not_enough_opinions",
            "stance_diversity_rate": 0.4,
            "temporal_coverage": "sufficient",
            "temporal_coverage_rate": 1.0,
            "traceability_rate": 0.8,
            "redundancy_rate": 0.2,
            "relevance": 0.8,
            "cost": 0.1,
        }
    return {
        "stakeholder_coverage": "sufficient",
        "stakeholder_coverage_rate": 1.0,
        "stance_diversity": "sufficient",
        "stance_diversity_rate": 1.0,
        "temporal_coverage": "sufficient",
        "temporal_coverage_rate": 1.0,
        "traceability_rate": 0.95,
        "redundancy_rate": 0.15,
        "relevance": 0.9,
        "cost": 0.1,
    }


def semireal_coverage_status(state: dict[str, Any]) -> dict[str, Any]:
    """Compute coverage status over normalized semi-real evidence."""
    evidence = list(state.get("evidence", []))
    if not evidence:
        return {
            "stakeholder_coverage": "stakeholder_missing",
            "stakeholder_coverage_rate": 0.0,
            "stance_diversity": "not_enough_opinions",
            "stance_diversity_rate": 0.0,
            "temporal_coverage": "insufficient",
            "temporal_coverage_rate": 0.0,
            "traceability_rate": 0.0,
            "redundancy_rate": 0.0,
            "relevance": 0.0,
            "cost": 0.0,
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
    time_stages = {
        str(item.get("metadata", {}).get("time_stage") or item.get("timestamp") or "unknown").strip().lower()
        for item in evidence
    }
    time_stages.discard("")
    time_stages.discard("unknown")
    traceable = [item for item in evidence if item.get("url") and item.get("evidence_id")]
    texts = [" ".join(str(item.get("text", "")).lower().split()) for item in evidence]
    duplicate_count = sum(count - 1 for count in Counter(texts).values() if count > 1)

    required_stakeholders = max(1, int(state.get("min_stakeholders", 2)))
    required_stances = max(1, int(state.get("min_stances", 2)))
    required_time_stages = max(1, int(state.get("min_time_stages", 2)))
    stakeholder_rate = min(1.0, len(stakeholders) / required_stakeholders)
    stance_rate = min(1.0, len(stances) / required_stances)
    temporal_rate = min(1.0, max(len(time_stages), 1 if len(evidence) == 1 else 0) / required_time_stages)
    traceability_rate = len(traceable) / len(evidence)
    redundancy_rate = duplicate_count / len(evidence)

    stakeholder_status = "sufficient" if stakeholder_rate >= 1.0 else "stakeholder_missing"
    stance_status = "sufficient" if stance_rate >= 1.0 else "not_enough_opinions"
    temporal_status = "sufficient" if temporal_rate >= 1.0 else "insufficient"
    if traceability_rate < float(state.get("min_traceability_rate", 0.8)):
        stakeholder_status = "stakeholder_missing"
    if redundancy_rate > float(state.get("max_redundancy_rate", 0.6)):
        stance_status = "not_enough_opinions"

    return {
        "stakeholder_coverage": stakeholder_status,
        "stakeholder_coverage_rate": round(stakeholder_rate, 4),
        "stance_diversity": stance_status,
        "stance_diversity_rate": round(stance_rate, 4),
        "temporal_coverage": temporal_status,
        "temporal_coverage_rate": round(temporal_rate, 4),
        "traceability_rate": round(traceability_rate, 4),
        "redundancy_rate": round(redundancy_rate, 4),
        "relevance": round(1.0 - redundancy_rate, 4),
        "cost": round(min(1.0, len(evidence) / max(1, int(state.get("max_evidence_per_event", 80)))), 4),
    }


def coverage_objective(status: dict[str, Any], state: dict[str, Any]) -> float:
    """Compute the paper-facing C-FSM coverage objective J."""
    weights = coverage_weights(state)
    return (
        weights["relevance"] * float(status.get("relevance", 0.0))
        + weights["stakeholder_coverage"] * float(status.get("stakeholder_coverage_rate", 0.0))
        + weights["stance_diversity"] * float(status.get("stance_diversity_rate", 0.0))
        + weights["temporal_coverage"] * float(status.get("temporal_coverage_rate", 0.0))
        + weights["traceability"] * float(status.get("traceability_rate", 0.0))
        - weights["redundancy"] * float(status.get("redundancy_rate", 0.0))
        - weights["cost"] * float(status.get("cost", 0.0))
    )


def default_coverage_weights() -> dict[str, float]:
    """Return the default C-FSM objective weights."""
    return dict(DEFAULT_COVERAGE_WEIGHTS)
