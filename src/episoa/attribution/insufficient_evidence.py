"""Helpers for insufficient-evidence attribution outputs."""

from __future__ import annotations

from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


def is_insufficient_evidence(evidence: list[EvidenceRecord]) -> bool:
    return len(evidence) == 0


__all__ = ["is_insufficient_evidence"]
