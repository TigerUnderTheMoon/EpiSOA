"""S0 event understanding for C-FSM evidence collection."""

from __future__ import annotations

from typing import Any

from episoa.collector.common import MAX_FEEDBACK_TRANSITIONS, collection_mode, visit


def event_understanding(state: dict[str, Any]) -> dict[str, Any]:
    """Understand event boundaries, aliases, time window, and target stakeholders."""
    target_event = state.get("target_event", "unknown event")
    aliases = [str(item).strip() for item in state.get("event_aliases", []) if str(item).strip()]
    stakeholders = [str(item).strip() for item in state.get("stakeholders", []) if str(item).strip()]
    time_window = state.get("time_window", {})
    window_text = ""
    if time_window:
        window_text = f" during {time_window.get('start', '?')} to {time_window.get('end', '?')}"

    if collection_mode(state) == "semireal_search":
        summary = f"Semi-real collection target: {target_event}{window_text}"
        if aliases:
            summary += f"; aliases={', '.join(aliases)}"
        if stakeholders:
            summary += f"; stakeholders={', '.join(stakeholders)}"
        return {
            "visited_states": visit(state, "event_understanding"),
            "event_summary": summary,
            "max_coverage_attempts": int(state.get("max_coverage_attempts", MAX_FEEDBACK_TRANSITIONS + 1)),
            "event_profile": {
                "target_event": target_event,
                "aliases": aliases,
                "stakeholders": stakeholders,
                "time_window": time_window,
            },
        }

    return {
        "visited_states": visit(state, "event_understanding"),
        "event_summary": f"Mock understanding for {target_event}",
        "event_profile": {
            "target_event": target_event,
            "aliases": aliases,
            "stakeholders": stakeholders,
            "time_window": time_window,
        },
    }
