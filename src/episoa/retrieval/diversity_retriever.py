"""Diversity-aware evidence retrieval for EpiSOA."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import exp
from pathlib import Path
from typing import Protocol

from episoa.retrieval.embedding_client import (
    EmbeddingClient,
    EmbeddingClientConfig,
    config_from_env,
    mock_similarity,
)
from episoa.schemas.evidence import EvidenceRecord


class EvidenceScorer(Protocol):
    """Replaceable scoring interface for evidence reranking."""

    def __call__(
        self,
        query: str,
        evidence: EvidenceRecord,
        selected: list[EvidenceRecord],
        evidence_pool: list[EvidenceRecord],
    ) -> float:
        """Score a candidate evidence item."""


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("-", " ").split() if token.strip()}


def _metadata_value(evidence: EvidenceRecord, key: str, default: str = "unknown") -> str:
    value = evidence.metadata.get(key, default)
    if value is None:
        return default
    return str(value).strip().lower() or default


def relevance_score(
    query: str,
    evidence: EvidenceRecord,
    selected: list[EvidenceRecord] | None = None,
    evidence_pool: list[EvidenceRecord] | None = None,
) -> float:
    """Embedding similarity score with a mock fallback for local tests."""
    return _default_relevance_scorer().score(query, evidence)


class MockRelevanceScorer:
    """Deterministic token-overlap scorer used by tests and fallback mode."""

    def score(self, query: str, evidence: EvidenceRecord) -> float:
        """Compute a simple lexical overlap score."""
        return mock_similarity(query, evidence.text)

    def __call__(
        self,
        query: str,
        evidence: EvidenceRecord,
        selected: list[EvidenceRecord] | None = None,
        evidence_pool: list[EvidenceRecord] | None = None,
    ) -> float:
        return self.score(query, evidence)


class EmbeddingRelevanceScorer(EmbeddingClient):
    """Backward-compatible wrapper around `EmbeddingClient`."""

    def __init__(
        self,
        *,
        mode: str = "mock",
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: str | Path = "outputs/cache/embeddings",
        reranker_mode: str = "mock",
        reranker_model_name: str = "BAAI/bge-reranker-base",
    ) -> None:
        embedding_mode = "sentence_transformers" if mode in {"sentence_transformers", "real"} else "mock"
        super().__init__(
            EmbeddingClientConfig(
                embedding_mode=embedding_mode,  # type: ignore[arg-type]
                embedding_model_name=model_name,
                reranker_mode=reranker_mode,  # type: ignore[arg-type]
                reranker_model_name=reranker_model_name,
                cache_dir=str(cache_dir),
            )
        )
        self.mode = embedding_mode
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)

    def score(self, query: str, evidence: EvidenceRecord) -> float:
        return self.relevance_score(query, evidence)

    def __call__(
        self,
        query: str,
        evidence: EvidenceRecord,
        selected: list[EvidenceRecord] | None = None,
        evidence_pool: list[EvidenceRecord] | None = None,
    ) -> float:
        return self.score(query, evidence)


def _default_relevance_scorer() -> EmbeddingRelevanceScorer:
    client_config = config_from_env()
    global _DEFAULT_RELEVANCE_SCORER
    if (
        _DEFAULT_RELEVANCE_SCORER is None
        or _DEFAULT_RELEVANCE_SCORER.mode != client_config.embedding_mode
        or _DEFAULT_RELEVANCE_SCORER.model_name != client_config.embedding_model_name
        or _DEFAULT_RELEVANCE_SCORER.cache_dir != Path(client_config.cache_dir)
        or _DEFAULT_RELEVANCE_SCORER.config.reranker_mode != client_config.reranker_mode
        or _DEFAULT_RELEVANCE_SCORER.config.reranker_model_name != client_config.reranker_model_name
    ):
        _DEFAULT_RELEVANCE_SCORER = EmbeddingRelevanceScorer(
            mode=client_config.embedding_mode,
            model_name=client_config.embedding_model_name,
            cache_dir=client_config.cache_dir,
            reranker_mode=client_config.reranker_mode,
            reranker_model_name=client_config.reranker_model_name,
        )
    return _DEFAULT_RELEVANCE_SCORER


_DEFAULT_RELEVANCE_SCORER: EmbeddingRelevanceScorer | None = None


def stakeholder_coverage_score(
    query: str,
    evidence: EvidenceRecord,
    selected: list[EvidenceRecord],
    evidence_pool: list[EvidenceRecord] | None = None,
) -> float:
    """Reward evidence from stakeholders not yet represented in selected results."""
    stakeholder = _metadata_value(evidence, "stakeholder")
    selected_stakeholders = {_metadata_value(item, "stakeholder") for item in selected}
    if stakeholder == "unknown":
        return 0.1
    return 1.0 if stakeholder not in selected_stakeholders else 0.2


def stance_diversity_score(
    query: str,
    evidence: EvidenceRecord,
    selected: list[EvidenceRecord],
    evidence_pool: list[EvidenceRecord] | None = None,
) -> float:
    """Reward evidence with a stance not yet represented in selected results."""
    stance = _metadata_value(evidence, "stance")
    selected_stances = {_metadata_value(item, "stance") for item in selected}
    if stance == "unknown":
        return 0.1
    return 1.0 if stance not in selected_stances else 0.3


def temporal_coverage_score(
    query: str,
    evidence: EvidenceRecord,
    selected: list[EvidenceRecord],
    evidence_pool: list[EvidenceRecord],
) -> float:
    """Reward timestamps that expand coverage across the candidate time span."""
    if not evidence_pool:
        return 0.0

    timestamps = [item.timestamp for item in evidence_pool]
    earliest = min(timestamps)
    latest = max(timestamps)
    total_seconds = (latest - earliest).total_seconds()
    if total_seconds <= 0:
        return 0.5

    position = (evidence.timestamp - earliest).total_seconds() / total_seconds
    if not selected:
        return 0.5 + 0.5 * abs(position - 0.5)

    selected_positions = [
        (item.timestamp - earliest).total_seconds() / total_seconds for item in selected
    ]
    nearest_distance = min(abs(position - selected_position) for selected_position in selected_positions)
    return min(1.0, nearest_distance * 2)


def redundancy_penalty(
    query: str,
    evidence: EvidenceRecord,
    selected: list[EvidenceRecord],
    evidence_pool: list[EvidenceRecord] | None = None,
) -> float:
    """Penalize evidence that is textually similar to already selected results."""
    evidence_tokens = _tokens(evidence.text)
    if not evidence_tokens or not selected:
        return 0.0

    max_similarity = 0.0
    for item in selected:
        selected_tokens = _tokens(item.text)
        if not selected_tokens:
            continue
        similarity = len(evidence_tokens & selected_tokens) / len(evidence_tokens | selected_tokens)
        max_similarity = max(max_similarity, similarity)
    return max_similarity


class DiversityAwareEvidenceRetriever:
    """Greedy reranker that balances relevance with stakeholder and stance diversity."""

    def __init__(
        self,
        *,
        relevance_weight: float = 1.0,
        stakeholder_weight: float = 0.85,
        stance_weight: float = 0.45,
        temporal_weight: float = 0.2,
        redundancy_weight: float = 0.9,
        relevance_scorer: EvidenceScorer = relevance_score,
        stakeholder_scorer: EvidenceScorer = stakeholder_coverage_score,
        stance_scorer: EvidenceScorer = stance_diversity_score,
        temporal_scorer: EvidenceScorer = temporal_coverage_score,
        redundancy_scorer: EvidenceScorer = redundancy_penalty,
    ) -> None:
        self.relevance_weight = relevance_weight
        self.stakeholder_weight = stakeholder_weight
        self.stance_weight = stance_weight
        self.temporal_weight = temporal_weight
        self.redundancy_weight = redundancy_weight
        self.relevance_scorer = relevance_scorer
        self.stakeholder_scorer = stakeholder_scorer
        self.stance_scorer = stance_scorer
        self.temporal_scorer = temporal_scorer
        self.redundancy_scorer = redundancy_scorer

    def score_candidate(
        self,
        query: str,
        evidence: EvidenceRecord,
        selected: list[EvidenceRecord],
        evidence_pool: list[EvidenceRecord],
    ) -> float:
        """Compute the weighted reranking score for one candidate."""
        return (
            self.relevance_weight * self.relevance_scorer(query, evidence, selected, evidence_pool)
            + self.stakeholder_weight * self.stakeholder_scorer(query, evidence, selected, evidence_pool)
            + self.stance_weight * self.stance_scorer(query, evidence, selected, evidence_pool)
            + self.temporal_weight * self.temporal_scorer(query, evidence, selected, evidence_pool)
            - self.redundancy_weight * self.redundancy_scorer(query, evidence, selected, evidence_pool)
        )

    def retrieve(
        self,
        query: str,
        evidence_pool: list[EvidenceRecord],
        top_k: int = 5,
    ) -> list[EvidenceRecord]:
        """Return a reranked evidence list for the query."""
        if top_k <= 0 or not evidence_pool:
            return []

        selected: list[EvidenceRecord] = []
        remaining = list(evidence_pool)
        limit = min(top_k, len(remaining))

        for _ in range(limit):
            best = max(
                remaining,
                key=lambda item: (
                    self.score_candidate(query, item, selected, evidence_pool),
                    item.timestamp,
                    item.evidence_id,
                ),
            )
            selected.append(best)
            remaining.remove(best)

        return selected


def retrieve(query: str, evidence_pool: list[EvidenceRecord], top_k: int = 5) -> list[EvidenceRecord]:
    """Convenience retrieval function using the default diversity-aware reranker."""
    return DiversityAwareEvidenceRetriever().retrieve(query, evidence_pool, top_k)


def stakeholder_distribution(evidence_list: list[EvidenceRecord]) -> Counter[str]:
    """Summarize stakeholder coverage for diagnostics and tests."""
    return Counter(_metadata_value(item, "stakeholder") for item in evidence_list)


def temporal_decay(reference: datetime, candidate: datetime, half_life_days: float = 30.0) -> float:
    """Small utility for future recency-aware scoring extensions."""
    seconds = abs((reference - candidate).total_seconds())
    half_life_seconds = half_life_days * 24 * 60 * 60
    if half_life_seconds <= 0:
        return 0.0
    return exp(-seconds / half_life_seconds)
