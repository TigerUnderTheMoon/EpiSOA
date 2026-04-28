"""Embedding and reranker clients for retrieval relevance scoring."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from episoa.schemas.evidence import EvidenceRecord


EmbeddingMode = Literal["mock", "sentence_transformers"]
RerankerMode = Literal["mock", "bge_reranker"]


@dataclass(frozen=True)
class EmbeddingClientConfig:
    """Configuration for retrieval embedding and reranker clients."""

    embedding_mode: EmbeddingMode = "mock"
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    reranker_mode: RerankerMode = "mock"
    reranker_model_name: str = "BAAI/bge-reranker-base"
    cache_dir: str = "outputs/cache/embeddings"


class EmbeddingClient:
    """Relevance scorer backed by mock overlap, sentence-transformers, or BGE reranker."""

    def __init__(self, config: EmbeddingClientConfig | dict | None = None) -> None:
        self.config = config if isinstance(config, EmbeddingClientConfig) else config_from_env(config or {})
        self._embedding_model = None
        self._reranker_model = None

    def relevance_score(self, query: str, evidence: EvidenceRecord) -> float:
        """Score query-evidence relevance using reranker first, then embedding similarity."""
        if self.config.reranker_mode == "bge_reranker":
            return self._bge_reranker_score(query, evidence)
        if self.config.embedding_mode == "sentence_transformers":
            return self._embedding_similarity(query, evidence)
        return mock_similarity(query, evidence.text)

    def _embedding_similarity(self, query: str, evidence: EvidenceRecord) -> float:
        model = self._load_embedding_model()
        query_embedding = _as_float_list(model.encode(query, normalize_embeddings=True))
        evidence_embedding = self.evidence_embedding(evidence)
        return _cosine_similarity(query_embedding, evidence_embedding)

    def evidence_embedding(self, evidence: EvidenceRecord) -> list[float]:
        """Return cached or newly encoded evidence embedding."""
        cache_path = self.cache_path(evidence)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return [float(value) for value in cached["embedding"]]

        model = self._load_embedding_model()
        embedding = _as_float_list(model.encode(evidence.text, normalize_embeddings=True))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "model_name": self.config.embedding_model_name,
                    "evidence_id": evidence.evidence_id,
                    "text_hash": text_hash(evidence.text),
                    "embedding": embedding,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return embedding

    def cache_path(self, evidence: EvidenceRecord) -> Path:
        """Cache path keyed by model_name + evidence_id + text_hash."""
        key = cache_key(self.config.embedding_model_name, evidence.evidence_id, evidence.text)
        return Path(self.config.cache_dir) / safe_model_name(self.config.embedding_model_name) / f"{key}.json"

    def _bge_reranker_score(self, query: str, evidence: EvidenceRecord) -> float:
        model = self._load_reranker_model()
        raw_score = model.predict([(query, evidence.text)])
        if hasattr(raw_score, "tolist"):
            raw_score = raw_score.tolist()
        if isinstance(raw_score, list):
            raw_score = raw_score[0]
        return _sigmoid(float(raw_score))

    def _load_embedding_model(self):
        _ensure_real_models_allowed("sentence_transformers")
        if self._embedding_model is not None:
            return self._embedding_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is required for embedding_mode=sentence_transformers") from exc
        self._embedding_model = SentenceTransformer(self.config.embedding_model_name)
        return self._embedding_model

    def _load_reranker_model(self):
        _ensure_real_models_allowed("bge_reranker")
        if self._reranker_model is not None:
            return self._reranker_model
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is required for reranker_mode=bge_reranker") from exc
        self._reranker_model = CrossEncoder(self.config.reranker_model_name)
        return self._reranker_model


class RerankerClient(EmbeddingClient):
    """Unified reranker interface backed by the retrieval client configuration."""

    def rerank(self, query: str, evidence_records: list[EvidenceRecord]) -> list[tuple[EvidenceRecord, float]]:
        """Return evidence records sorted by descending reranker score."""
        scored = [(evidence, self.relevance_score(query, evidence)) for evidence in evidence_records]
        return sorted(scored, key=lambda item: (item[1], item[0].timestamp, item[0].evidence_id), reverse=True)


def config_from_env(overrides: dict | None = None) -> EmbeddingClientConfig:
    """Build embedding config from environment plus optional overrides."""
    raw = overrides or {}
    embedding_mode = str(raw.get("embedding_mode") or os.getenv("EPISOA_EMBEDDING_MODE", "mock")).strip()
    reranker_mode = str(raw.get("reranker_mode") or os.getenv("EPISOA_RERANKER_MODE", "mock")).strip()
    if os.getenv("EPISOA_TESTING") == "1":
        if embedding_mode != "sentence_transformers":
            embedding_mode = "mock"
        if reranker_mode != "bge_reranker":
            reranker_mode = "mock"
    if embedding_mode not in {"mock", "sentence_transformers"}:
        raise ValueError("embedding_mode must be one of: mock, sentence_transformers")
    if reranker_mode not in {"mock", "bge_reranker"}:
        raise ValueError("reranker_mode must be one of: mock, bge_reranker")
    return EmbeddingClientConfig(
        embedding_mode=embedding_mode,  # type: ignore[arg-type]
        embedding_model_name=str(raw.get("embedding_model_name") or os.getenv("EPISOA_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")),
        reranker_mode=reranker_mode,  # type: ignore[arg-type]
        reranker_model_name=str(raw.get("reranker_model_name") or os.getenv("EPISOA_RERANKER_MODEL", "BAAI/bge-reranker-base")),
        cache_dir=str(raw.get("cache_dir") or os.getenv("EPISOA_EMBEDDING_CACHE_DIR", "outputs/cache/embeddings")),
    )


def mock_similarity(query: str, text: str) -> float:
    """Deterministic lexical overlap score used in mock mode."""
    query_tokens = tokens(query)
    text_tokens = tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens | text_tokens)


def tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("-", " ").split() if token.strip()}


def cache_key(model_name: str, evidence_id: str, text: str) -> str:
    return hashlib.sha256("|".join([model_name, evidence_id, text_hash(text)]).encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_model_name(model_name: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in model_name)


def _ensure_real_models_allowed(mode: str) -> None:
    if os.getenv("EPISOA_TESTING") == "1" and os.getenv("EPISOA_ALLOW_REAL_MODEL_TESTS") != "1":
        raise RuntimeError(f"{mode} cannot load real models during pytest unless EPISOA_ALLOW_REAL_MODEL_TESTS=1")


def _as_float_list(values) -> list[float]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    return [float(value) for value in values]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = pow(2.718281828459045, -value)
        return 1.0 / (1.0 + z)
    z = pow(2.718281828459045, value)
    return z / (1.0 + z)
