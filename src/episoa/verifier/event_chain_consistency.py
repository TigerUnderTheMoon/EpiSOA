"""Event-chain consistency checks for attribution tuples."""

from __future__ import annotations

from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("-", " ").split() if token.strip()}


def event_chain_consistency_score(
    attribution: AttributionTuple,
    evidence_records: list[EvidenceRecord],
) -> float:
    """Score whether event-chain events are grounded in the evidence."""
    if not evidence_records or not attribution.event_chain:
        return 0.0

    evidence_text = " ".join(
        [
            *(item.text for item in evidence_records),
            *(str(item.metadata.get("event", "")) for item in evidence_records),
        ]
    )
    evidence_tokens = _tokens(evidence_text)
    if not evidence_tokens:
        return 0.0

    covered = 0
    for event in attribution.event_chain:
        event_tokens = _tokens(event)
        if event_tokens and event_tokens & evidence_tokens:
            covered += 1

    return covered / len(attribution.event_chain)
