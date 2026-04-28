"""Stakeholder consistency checks for attribution tuples."""

from __future__ import annotations

from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


def _normalize(value: object) -> str:
    return str(value or "").strip().lower()


def stakeholder_consistency_score(
    attribution: AttributionTuple,
    evidence_records: list[EvidenceRecord],
) -> float:
    """Score whether evidence refers to the attributed stakeholder."""
    if not evidence_records:
        return 0.0

    expected = _normalize(attribution.stakeholder)
    matches = 0
    for evidence in evidence_records:
        candidate = _normalize(evidence.metadata.get("stakeholder") or evidence.author_alias)
        text = _normalize(evidence.text)
        if candidate == expected or expected in text:
            matches += 1

    return matches / len(evidence_records)
