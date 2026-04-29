"""Path-level reranking for EventRAG retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from episoa.eventrag.evidence_backtracking import EvidenceBackedPath
from episoa.eventrag.evidence_backtracking import backtrack_evidence
from episoa.eventrag.anchor_selection import select_anchor_events
from episoa.eventrag.chain_expansion import expand_event_chains
from episoa.eventrag.query_to_event import _tokens, parse_query_to_event
from episoa.graph_builder.graph_store import EvidenceGraph
from episoa.schemas.graph import EventChain


@dataclass(frozen=True)
class ScoredEventPath:
    """A path with decomposed score features."""

    path: EvidenceBackedPath
    score: float
    relevance: float
    evidence_support: float
    stakeholder_coverage: float
    temporal_coherence: float
    causal_plausibility: float
    redundancy: float


def score_path(
    query: str,
    evidence_graph: EvidenceGraph,
    path: EvidenceBackedPath,
    *,
    lambda_1: float = 1.0,
    lambda_2: float = 1.0,
    lambda_3: float = 0.5,
    lambda_4: float = 0.7,
    lambda_5: float = 0.7,
    lambda_6: float = 0.4,
    use_stakeholder_constraint: bool = True,
    use_temporal_information: bool = True,
) -> ScoredEventPath:
    """Score a path with the requested EventRAG formula."""
    relevance = _path_relevance(query, evidence_graph, path)
    evidence_support = min(1.0, len(path.evidence) / max(1, len(path.path.node_ids)))
    stakeholder_coverage = min(1.0, len(set(path.stakeholders)) / 3) if use_stakeholder_constraint else 0.0
    temporal_coherence = _temporal_coherence(path) if use_temporal_information else 0.0
    causal_plausibility = _causal_plausibility(path)
    redundancy = _redundancy(path)
    score = (
        lambda_1 * relevance
        + lambda_2 * evidence_support
        + lambda_3 * stakeholder_coverage
        + lambda_4 * temporal_coherence
        + lambda_5 * causal_plausibility
        - lambda_6 * redundancy
    )

    return ScoredEventPath(
        path=path,
        score=score,
        relevance=relevance,
        evidence_support=evidence_support,
        stakeholder_coverage=stakeholder_coverage,
        temporal_coherence=temporal_coherence,
        causal_plausibility=causal_plausibility,
        redundancy=redundancy,
    )


def rerank_paths(
    query: str,
    evidence_graph: EvidenceGraph,
    paths: list[EvidenceBackedPath],
    top_k: int = 5,
    scoring_weights: dict[str, Any] | None = None,
    use_stakeholder_constraint: bool = True,
    use_temporal_information: bool = True,
) -> list[ScoredEventPath]:
    """Rank evidence-backed paths by path-level score."""
    weights = scoring_weights or {}
    scored = [
        score_path(
            query,
            evidence_graph,
            path,
            lambda_1=float(weights.get("lambda_1", 1.0)),
            lambda_2=float(weights.get("lambda_2", 1.0)),
            lambda_3=float(weights.get("lambda_3", 0.5)),
            lambda_4=float(weights.get("lambda_4", 0.7)),
            lambda_5=float(weights.get("lambda_5", 0.7)),
            lambda_6=float(weights.get("lambda_6", 0.4)),
            use_stakeholder_constraint=use_stakeholder_constraint,
            use_temporal_information=use_temporal_information,
        )
        for path in paths
    ]
    return sorted(scored, key=lambda item: item.score, reverse=True)[: max(top_k, 0)]


def scored_path_to_event_chain(evidence_graph: EvidenceGraph, scored_path: ScoredEventPath) -> EventChain:
    """Convert a scored graph path into the public EventChain schema."""
    event_labels = [
        str(evidence_graph.graph.nodes[node_id].get("label", node_id))
        for node_id in scored_path.path.path.node_ids
    ]
    return EventChain(
        target_event=event_labels[0],
        event_chain=event_labels,
        stakeholders=list(scored_path.path.stakeholders) or ["unknown"],
        candidate_rationales=[
            (
                f"path_score={scored_path.score:.3f}; relevance={scored_path.relevance:.3f}; "
                f"evidence_support={scored_path.evidence_support:.3f}; "
                f"stakeholder_coverage={scored_path.stakeholder_coverage:.3f}; "
                f"temporal_coherence={scored_path.temporal_coherence:.3f}; "
                f"causal_plausibility={scored_path.causal_plausibility:.3f}; "
                f"redundancy={scored_path.redundancy:.3f}"
            )
        ],
        evidence=list(scored_path.path.evidence),
    )


def retrieve_event_chains(
    query: str,
    evidence_graph: EvidenceGraph,
    *,
    depth: int = 2,
    top_k: int = 5,
    anchor_top_k: int = 3,
    scoring_weights: dict[str, Any] | None = None,
    use_stakeholder_constraint: bool = True,
    use_temporal_information: bool = True,
) -> list[EventChain]:
    """Run the complete EventRAG retrieval pipeline and return EventChain schemas."""
    query_event = parse_query_to_event(query)
    anchors = select_anchor_events(query_event, evidence_graph, top_k=anchor_top_k)
    paths = expand_event_chains(evidence_graph, anchors, depth=depth)
    evidence_backed_paths = [backtrack_evidence(evidence_graph, path) for path in paths]
    scored_paths = rerank_paths(
        query,
        evidence_graph,
        evidence_backed_paths,
        top_k=top_k,
        scoring_weights=scoring_weights,
        use_stakeholder_constraint=use_stakeholder_constraint,
        use_temporal_information=use_temporal_information,
    )
    return [scored_path_to_event_chain(evidence_graph, scored_path) for scored_path in scored_paths]


def _path_relevance(query: str, evidence_graph: EvidenceGraph, path: EvidenceBackedPath) -> float:
    query_tokens = _tokens(query)
    path_text = " ".join(
        str(evidence_graph.graph.nodes[node_id].get("label", node_id))
        for node_id in path.path.node_ids
    )
    path_tokens = _tokens(path_text)
    if not query_tokens or not path_tokens:
        return 0.0
    return len(query_tokens & path_tokens) / len(query_tokens | path_tokens)


def _temporal_coherence(path: EvidenceBackedPath) -> float:
    timestamps = list(path.timestamps)
    if len(timestamps) < 2:
        return 0.5 if timestamps else 0.0
    return 1.0 if timestamps == sorted(timestamps) else 0.0


def _causal_plausibility(path: EvidenceBackedPath) -> float:
    if not path.path.edge_types:
        return 0.0
    plausible_edges = {"precedes", "triggers", "responds_to", "amplifies", "caused_by"}
    return sum(edge in plausible_edges for edge in path.path.edge_types) / len(path.path.edge_types)


def _redundancy(path: EvidenceBackedPath) -> float:
    texts = [record.text.strip().lower() for record in path.evidence if record.text.strip()]
    if len(texts) <= 1:
        return 0.0
    return 1.0 - (len(set(texts)) / len(texts))
