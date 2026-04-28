"""Graph retrieval baseline using the evidence graph without EventRAG."""

from __future__ import annotations

from typing import Any

from episoa.baselines.direct_llm import event_chain_from_evidence, event_description_from
from episoa.graph_builder.extractor import build_evidence_graph
from episoa.reasoner.attribution_reasoner import reason_attribution
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.verifier.evidence_support import verify_attributions


def run(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    """Run graph-only retrieval without EventRAG-style chain retrieval."""
    config = config or {}
    llm_client = config.get("llm_client")
    verifier_threshold = float(config.get("verifier_threshold", 0.75))
    top_k = int(config.get("top_k", 5))
    event_description = event_description_from(event)
    graph = build_evidence_graph(evidence_pool)
    selected_evidence = _select_evidence_from_graph(graph, evidence_pool, top_k)
    event_chain = event_chain_from_evidence(event_description, selected_evidence)
    attributions = reason_attribution(event_chain, selected_evidence, event_description, llm_client=llm_client)
    return verify_attributions(
        attributions,
        selected_evidence,
        llm_client=llm_client,
        threshold=verifier_threshold,
    )


def run_baseline(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    return run(event, evidence_pool, config)


def _select_evidence_from_graph(graph, evidence_pool: list[EvidenceRecord], top_k: int) -> list[EvidenceRecord]:
    evidence_by_id = {item.evidence_id: item for item in evidence_pool}
    scored: list[tuple[int, str]] = []
    for node_id, attrs in graph.nodes_by_type("Evidence"):
        evidence_id = str(attrs.get("evidence_id") or node_id.removeprefix("evidence:"))
        degree = graph.graph.in_degree(node_id) + graph.graph.out_degree(node_id)
        scored.append((degree, evidence_id))
    selected_ids = [
        evidence_id
        for _, evidence_id in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)
        if evidence_id in evidence_by_id
    ]
    if not selected_ids:
        return evidence_pool[:top_k]
    return [evidence_by_id[evidence_id] for evidence_id in selected_ids[:top_k]]
