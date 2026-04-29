"""S2 source selection for C-FSM evidence collection."""

from __future__ import annotations

from typing import Any

from episoa.collector.common import SUPPORTED_SEMIREAL_SOURCES, collection_mode, visit


def source_selection(state: dict[str, Any]) -> dict[str, Any]:
    """Select source families while respecting configured source scope."""
    if collection_mode(state) == "semireal_search":
        requested = [str(item) for item in state.get("source_types", []) or state.get("source_scope", [])]
        selected = [item for item in requested if item in SUPPORTED_SEMIREAL_SOURCES]
        if not selected:
            selected = list(SUPPORTED_SEMIREAL_SOURCES)
        return {
            "visited_states": visit(state, "source_selection"),
            "selected_sources": selected,
        }
    return {
        "visited_states": visit(state, "source_selection"),
        "selected_sources": ["news", "social_media", "official"],
    }
