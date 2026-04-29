"""S4 opinion collection for C-FSM evidence collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from episoa.collector.common import collection_mode, source_type_for_evidence, visit


def browser_based_opinion_collection(state: dict[str, Any]) -> dict[str, Any]:
    """Extract opinion-like snippets from collected pages without opening browsers in tests."""
    if collection_mode(state) == "semireal_search":
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
                    "source_type": source_type_for_evidence(str(page.get("source") or "public_web")),
                    "metadata": {
                        **metadata,
                        "stakeholder": metadata.get("stakeholder", page.get("stakeholder", "unknown")),
                        "stance": metadata.get("stance", page.get("stance", metadata.get("sentiment", "unknown"))),
                        "sentiment": metadata.get("sentiment", page.get("sentiment", "unknown")),
                        "event": metadata.get("event", state.get("target_event", "unknown event")),
                        "query": page.get("query"),
                        "source_family": page.get("source", "public_web"),
                        "source_scope": metadata.get("source_scope", page.get("source", "public_web")),
                        "time_stage": metadata.get("time_stage", page.get("time_stage", "unknown")),
                    },
                }
            )
        return {
            "visited_states": visit(state, "browser_based_opinion_collection"),
            "opinions": opinions,
        }

    return {
        "visited_states": visit(state, "browser_based_opinion_collection"),
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
