"""NetworkX-backed evidence graph store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import networkx as nx


NodeType = Literal["Event", "Stakeholder", "Opinion", "Sentiment", "Rationale", "Evidence", "Time"]
EdgeType = Literal[
    "expresses",
    "has_sentiment",
    "caused_by",
    "evidenced_by",
    "appears_at",
    "precedes",
    "triggers",
    "responds_to",
    "amplifies",
]

VALID_NODE_TYPES: set[str] = {
    "Event",
    "Stakeholder",
    "Opinion",
    "Sentiment",
    "Rationale",
    "Evidence",
    "Time",
}
VALID_EDGE_TYPES: set[str] = {
    "expresses",
    "has_sentiment",
    "caused_by",
    "evidenced_by",
    "appears_at",
    "precedes",
    "triggers",
    "responds_to",
    "amplifies",
}


@dataclass
class EvidenceGraph:
    """Lightweight directed evidence graph with typed nodes and edges."""

    graph: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)

    def add_node(self, node_id: str, node_type: NodeType, **attrs: Any) -> None:
        """Add a typed node to the graph."""
        if not node_id.strip():
            raise ValueError("node_id must not be blank")
        if node_type not in VALID_NODE_TYPES:
            raise ValueError(f"Unsupported node type: {node_type}")

        self.graph.add_node(node_id, node_type=node_type, **attrs)

    def add_edge(self, source: str, target: str, edge_type: EdgeType, **attrs: Any) -> None:
        """Add a typed directed edge to the graph."""
        if source not in self.graph:
            raise ValueError(f"Missing source node: {source}")
        if target not in self.graph:
            raise ValueError(f"Missing target node: {target}")
        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(f"Unsupported edge type: {edge_type}")

        self.graph.add_edge(source, target, edge_type=edge_type, **attrs)

    def nodes_by_type(self, node_type: NodeType) -> list[tuple[str, dict[str, Any]]]:
        """Return all nodes of a given type with their attributes."""
        return [
            (node_id, attrs)
            for node_id, attrs in self.graph.nodes(data=True)
            if attrs.get("node_type") == node_type
        ]

    def edges_by_type(self, edge_type: EdgeType) -> list[tuple[str, str, dict[str, Any]]]:
        """Return all edges of a given type with their attributes."""
        return [
            (source, target, attrs)
            for source, target, attrs in self.graph.edges(data=True)
            if attrs.get("edge_type") == edge_type
        ]

    def has_evidence(self, evidence_id: str) -> bool:
        """Check whether an evidence node exists in the graph."""
        return f"evidence:{evidence_id}" in self.graph

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()
