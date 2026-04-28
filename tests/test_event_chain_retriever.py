from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

import episoa.retrieval.diversity_retriever as diversity_retriever
from episoa.retrieval.diversity_retriever import EmbeddingRelevanceScorer, retrieve
from episoa.retrieval.embedding_client import EmbeddingClient, EmbeddingClientConfig, cache_key
from episoa.schemas.evidence import EvidenceRecord


def setup_function() -> None:
    diversity_retriever._DEFAULT_RELEVANCE_SCORER = None


def make_evidence(
    evidence_id: str,
    text: str,
    stakeholder: str,
    stance: str,
    day: int,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        platform="Example",
        url=f"https://example.com/{evidence_id}",
        timestamp=datetime(2026, 4, day, tzinfo=timezone.utc),
        text=text,
        author_alias=None,
        source_type="news",
        metadata={"stakeholder": stakeholder, "stance": stance},
    )


def test_reranking_improves_stakeholder_coverage(monkeypatch) -> None:
    monkeypatch.setenv("EPISOA_EMBEDDING_MODE", "mock")
    evidence_pool = [
        make_evidence("ev-1", "policy change price increase customer reaction", "customers", "negative", 1),
        make_evidence("ev-2", "policy change price increase customer reaction repeated", "customers", "negative", 2),
        make_evidence("ev-3", "policy change employee operational concerns", "employees", "mixed", 3),
        make_evidence("ev-4", "policy change regulator compliance review", "regulators", "neutral", 4),
    ]

    result = retrieve("policy change price increase reaction", evidence_pool, top_k=3)
    stakeholders = {item.metadata["stakeholder"] for item in result}

    assert len(stakeholders) == 3
    assert result[0].evidence_id == "ev-1"


def test_reranking_reduces_duplicate_evidence(monkeypatch) -> None:
    monkeypatch.setenv("EPISOA_EMBEDDING_MODE", "mock")
    evidence_pool = [
        make_evidence("ev-1", "policy change price increase customer complaint", "customers", "negative", 1),
        make_evidence("ev-2", "policy change price increase customer complaint", "customers", "negative", 2),
        make_evidence("ev-3", "policy change price increase customer complaint", "customers", "negative", 3),
        make_evidence("ev-4", "policy change employee scheduling concern", "employees", "mixed", 4),
    ]

    result = retrieve("policy change price increase complaint", evidence_pool, top_k=3)
    result_ids = [item.evidence_id for item in result]

    assert "ev-4" in result_ids
    assert len({" ".join(item.text.split()) for item in result}) > 1


def test_top_k_return_format_is_stable(monkeypatch) -> None:
    monkeypatch.setenv("EPISOA_EMBEDDING_MODE", "mock")
    evidence_pool = [
        make_evidence("ev-1", "policy change customer reaction", "customers", "negative", 1),
        make_evidence("ev-2", "policy change employee concern", "employees", "mixed", 2),
    ]

    result = retrieve("policy change", evidence_pool, top_k=5)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(item, EvidenceRecord) for item in result)
    assert [item.evidence_id for item in result] == ["ev-2", "ev-1"]


def test_auto_embedding_mode_is_mock_during_pytest(monkeypatch) -> None:
    monkeypatch.setenv("EPISOA_TESTING", "1")
    monkeypatch.setenv("EPISOA_EMBEDDING_MODE", "auto")
    diversity_retriever._DEFAULT_RELEVANCE_SCORER = None

    scorer = diversity_retriever._default_relevance_scorer()

    assert scorer.mode == "mock"


@pytest.mark.integration
@pytest.mark.real_model
def test_real_embedding_mode_caches_evidence_embedding(monkeypatch) -> None:
    monkeypatch.setenv("EPISOA_ALLOW_REAL_MODEL_TESTS", "1")

    class FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def encode(self, text: str, normalize_embeddings: bool = True):
            if "customer" in text.lower():
                return [1.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    evidence = make_evidence("ev-1", "customer reaction to policy change", "customers", "negative", 1)
    model_name = f"fake-bge-{uuid4().hex}"
    cache_dir = Path("outputs/cache/embeddings/test")
    scorer = EmbeddingRelevanceScorer(
        mode="sentence_transformers",
        model_name=model_name,
        cache_dir=cache_dir,
    )

    first_score = scorer.score("customer policy", evidence)
    second_score = scorer.score("customer policy", evidence)
    cache_files = list((cache_dir / model_name).glob("*.json"))

    assert first_score == second_score
    assert first_score > 0
    assert len(cache_files) == 1


def test_cache_key_uses_model_evidence_id_and_text_hash() -> None:
    first = cache_key("model-a", "ev-1", "same text")
    same = cache_key("model-a", "ev-1", "same text")
    changed_text = cache_key("model-a", "ev-1", "different text")
    changed_id = cache_key("model-a", "ev-2", "same text")
    changed_model = cache_key("model-b", "ev-1", "same text")

    assert first == same
    assert len({first, changed_text, changed_id, changed_model}) == 4


@pytest.mark.integration
@pytest.mark.real_model
def test_bge_reranker_mode_uses_cross_encoder(monkeypatch) -> None:
    monkeypatch.setenv("EPISOA_ALLOW_REAL_MODEL_TESTS", "1")

    class FakeCrossEncoder:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def predict(self, pairs):
            query, text = pairs[0]
            return [2.0 if "policy" in query and "policy" in text else -2.0]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=FakeCrossEncoder),
    )
    evidence = make_evidence("ev-rerank", "policy change customer reaction", "customers", "negative", 1)
    client = EmbeddingClient(
        EmbeddingClientConfig(
            embedding_mode="mock",
            reranker_mode="bge_reranker",
            reranker_model_name=f"fake-reranker-{uuid4().hex}",
        )
    )

    score = client.relevance_score("policy reaction", evidence)

    assert score > 0.5
