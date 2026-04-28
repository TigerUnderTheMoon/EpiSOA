"""Evidence backtracking for EventRAG paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from episoa.eventrag.chain_expansion import EventPath
from episoa.graph_builder.graph_store import EvidenceGraph
from episoa.schemas.evidence import EvidenceRecord


@dataclass(frozen=True)
class EvidenceBackedPath:
    """An event path enriched with evidence and stakeholders."""

    path: EventPath
    evidence: tuple[EvidenceRecord, ...]
    stakeholders: tuple[str, ...]
    timestamps: tuple[datetime, ...]


def backtrack_evidence(evidence_graph: EvidenceGraph, event_path: EventPath) -> EvidenceBackedPath:
    """Collect evidence records and stakeholders connected to a graph path."""
    evidence_ids: set[str] = set()
    ordered_evidence_ids: list[str] = []

    def add_evidence_id(value: object) -> None:
        if not value:
            return
        evidence_id = str(value)
        if evidence_id in evidence_ids:
            return
        evidence_ids.add(evidence_id)
        ordered_evidence_ids.append(evidence_id)

    for event_id in event_path.node_ids:
        for _, target_id, attrs in evidence_graph.graph.out_edges(event_id, data=True):
            if attrs.get("edge_type") == "evidenced_by":
                add_evidence_id(attrs.get("evidence_id") or target_id.removeprefix("evidence:"))

    for source, target in zip(event_path.node_ids, event_path.node_ids[1:]):
        edge_data = evidence_graph.graph.get_edge_data(source, target, default={})
        for attrs in edge_data.values():
            add_evidence_id(attrs.get("evidence_id"))

    evidence = tuple(
        record
        for evidence_id in ordered_evidence_ids
        if (record := _evidence_record_from_graph(evidence_graph, evidence_id)) is not None
    )
    timestamps = tuple(record.timestamp for record in evidence)
    stakeholders = tuple(sorted(_stakeholders_for_evidence(evidence_graph, evidence_ids)))

    return EvidenceBackedPath(
        path=event_path,
        evidence=evidence,
        stakeholders=stakeholders,
        timestamps=timestamps,
    )


def _evidence_record_from_graph(evidence_graph: EvidenceGraph, evidence_id: str) -> EvidenceRecord | None:
    node_id = f"evidence:{evidence_id}"
    if node_id not in evidence_graph.graph:
        return None

    attrs: dict[str, Any] = evidence_graph.graph.nodes[node_id]
    timestamp = _timestamp_for_evidence(evidence_graph, node_id)
    return EvidenceRecord(
        evidence_id=str(attrs.get("evidence_id", evidence_id)),
        platform=str(attrs.get("platform", "unknown")),
        url=str(attrs.get("url", f"https://example.com/evidence/{evidence_id}")),
        timestamp=timestamp,
        text=str(attrs.get("text", f"Evidence {evidence_id}")),
        author_alias=attrs.get("author_alias"),
        source_type=attrs.get("source_type", "other"),
        metadata=dict(attrs.get("metadata", {})),
    )


def _timestamp_for_evidence(evidence_graph: EvidenceGraph, evidence_node_id: str) -> datetime:
    for _, time_node, attrs in evidence_graph.graph.out_edges(evidence_node_id, data=True):
        if attrs.get("edge_type") != "appears_at":
            continue
        label = str(evidence_graph.graph.nodes[time_node].get("label", ""))
        try:
            return datetime.fromisoformat(label)
        except ValueError:
            continue
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _stakeholders_for_evidence(evidence_graph: EvidenceGraph, evidence_ids: set[str]) -> set[str]:
    stakeholders: set[str] = set()
    for source, _, attrs in evidence_graph.graph.edges(data=True):
        if attrs.get("edge_type") != "expresses":
            continue
        if str(attrs.get("evidence_id")) not in evidence_ids:
            continue
        source_attrs = evidence_graph.graph.nodes[source]
        if source_attrs.get("node_type") == "Stakeholder":
            stakeholders.add(str(source_attrs.get("label", source)))
    return stakeholders
