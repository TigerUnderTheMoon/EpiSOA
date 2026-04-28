"""Sentiment consistency checks for attribution tuples."""

from __future__ import annotations

from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


POSITIVE_WORDS = {"support", "supports", "supported", "positive", "approve", "approved", "benefit"}
NEGATIVE_WORDS = {"oppose", "opposes", "opposed", "negative", "concern", "concerns", "criticize", "criticized"}


def _normalize(value: object) -> str:
    return str(value or "").strip().lower()


def _infer_sentiment(evidence: EvidenceRecord) -> str:
    metadata_sentiment = _normalize(evidence.metadata.get("sentiment") or evidence.metadata.get("stance"))
    if metadata_sentiment in {"positive", "negative", "neutral", "mixed", "unknown"}:
        return metadata_sentiment

    words = set(_normalize(evidence.text).replace("-", " ").split())
    if words & POSITIVE_WORDS and words & NEGATIVE_WORDS:
        return "mixed"
    if words & POSITIVE_WORDS:
        return "positive"
    if words & NEGATIVE_WORDS:
        return "negative"
    return "unknown"


def sentiment_consistency_score(
    attribution: AttributionTuple,
    evidence_records: list[EvidenceRecord],
) -> float:
    """Score whether evidence sentiment agrees with the attribution sentiment."""
    if not evidence_records:
        return 0.0
    if attribution.sentiment == "unknown":
        return 0.5

    matches = 0
    for evidence in evidence_records:
        inferred = _infer_sentiment(evidence)
        if inferred == attribution.sentiment:
            matches += 1
        elif attribution.sentiment == "mixed" and inferred in {"positive", "negative", "neutral"}:
            matches += 0.5
        elif inferred == "unknown":
            matches += 0.25

    return min(1.0, matches / len(evidence_records))
