"""Vanilla RAG baseline using relevance-only evidence ranking."""

from __future__ import annotations

from typing import Any

from episoa.baselines.direct_llm import event_chain_from_evidence, event_description_from
from episoa.reasoner.attribution_reasoner import reason_attribution
from episoa.retrieval.diversity_retriever import relevance_score
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.verifier.evidence_support import verify_attributions


def run(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    """Run a relevance-only RAG baseline."""
    config = config or {}
    llm_client = config.get("llm_client")
    verifier_threshold = float(config.get("verifier_threshold", 0.75))
    event_description = event_description_from(event)
    top_k = int(config.get("top_k", 5))
    ranked_evidence = sorted(
        evidence_pool,
        key=lambda item: (relevance_score(event_description, item), item.timestamp, item.evidence_id),
        reverse=True,
    )[:top_k]
    event_chain = event_chain_from_evidence(event_description, ranked_evidence)
    attributions = reason_attribution(event_chain, ranked_evidence, event_description, llm_client=llm_client)
    return verify_attributions(
        attributions,
        ranked_evidence,
        llm_client=llm_client,
        threshold=verifier_threshold,
    )


def run_baseline(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    return run(event, evidence_pool, config)
