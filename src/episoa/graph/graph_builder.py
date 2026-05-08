"""Build the Stakeholder-Event Evidence Graph."""

from __future__ import annotations

from episoa.data.schema import EventRecord, EvidenceRecord
from episoa.graph.evidence_graph import EvidenceGraph, GraphEdge, GraphNode


def build_graph(events: list[EventRecord], evidence: list[EvidenceRecord]) -> EvidenceGraph:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    for event in events:
        nodes[f"event:{event.event_id}"] = GraphNode(f"event:{event.event_id}", "event", event.text)
    for item in evidence:
        evidence_node = f"evidence:{item.evidence_id}"
        nodes[evidence_node] = GraphNode(evidence_node, "evidence", item.evidence_id)
        edges.append(GraphEdge(evidence_node, f"event:{item.event_id}", "supports", item.evidence_id))
    return EvidenceGraph(list(nodes.values()), edges)
