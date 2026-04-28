"""Anchor event selection for EventRAG retrieval."""

from __future__ import annotations

from episoa.eventrag.query_to_event import QueryEvent
from episoa.graph_builder.graph_store import EvidenceGraph


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("-", " ").split() if token.strip()}


def _overlap_score(query_tokens: set[str], label: str) -> float:
    label_tokens = _tokens(label)
    if not query_tokens or not label_tokens:
        return 0.0
    return len(query_tokens & label_tokens) / len(query_tokens | label_tokens)


def select_anchor_events(
    query_event: QueryEvent,
    evidence_graph: EvidenceGraph,
    top_k: int = 3,
) -> list[str]:
    """Select event nodes that best match the parsed query."""
    event_nodes = evidence_graph.nodes_by_type("Event")
    ranked = sorted(
        event_nodes,
        key=lambda item: (
            _overlap_score(query_event.keywords, str(item[1].get("label", item[0]))),
            str(item[1].get("label", item[0])),
        ),
        reverse=True,
    )
    return [node_id for node_id, _ in ranked[: max(top_k, 0)]]
