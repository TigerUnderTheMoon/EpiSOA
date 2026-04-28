"""Event-chain expansion over an evidence graph."""

from __future__ import annotations

from dataclasses import dataclass

from episoa.graph_builder.graph_store import EvidenceGraph


EXPANSION_EDGE_TYPES = {"precedes", "triggers", "responds_to", "amplifies", "caused_by"}


@dataclass(frozen=True)
class EventPath:
    """A graph path over event nodes."""

    node_ids: tuple[str, ...]
    edge_types: tuple[str, ...]


def expand_event_chains(
    evidence_graph: EvidenceGraph,
    anchor_event_ids: list[str],
    depth: int = 2,
) -> list[EventPath]:
    """Expand anchor events into event paths using causal and temporal edges."""
    max_depth = min(max(depth, 1), 3)
    paths: list[EventPath] = []

    for anchor_id in anchor_event_ids:
        if anchor_id not in evidence_graph.graph:
            continue
        _expand_from(evidence_graph, anchor_id, (anchor_id,), (), max_depth, paths)

    return paths


def _expand_from(
    evidence_graph: EvidenceGraph,
    current_id: str,
    node_path: tuple[str, ...],
    edge_path: tuple[str, ...],
    remaining_depth: int,
    paths: list[EventPath],
) -> None:
    if edge_path:
        paths.append(EventPath(node_ids=node_path, edge_types=edge_path))
    if remaining_depth == 0:
        return

    for _, target_id, attrs in evidence_graph.graph.out_edges(current_id, data=True):
        edge_type = attrs.get("edge_type")
        if edge_type not in EXPANSION_EDGE_TYPES:
            continue
        if target_id in node_path:
            continue
        if evidence_graph.graph.nodes[target_id].get("node_type") != "Event":
            continue
        _expand_from(
            evidence_graph,
            target_id,
            (*node_path, target_id),
            (*edge_path, str(edge_type)),
            remaining_depth - 1,
            paths,
        )
