"""Evidence normalization with privacy protection."""

from __future__ import annotations

from typing import Any

from episoa.collector.privacy_filter import normalize_private_evidence, privacy_filter_raw_evidence
from episoa.schemas.evidence import EvidenceRecord


def normalize_evidence(raw: dict[str, Any]) -> EvidenceRecord:
    """Normalize one raw evidence item into a privacy-safe EvidenceRecord."""
    return normalize_private_evidence(raw)


def normalize_evidence_batch(raw_items: list[dict[str, Any]]) -> list[EvidenceRecord]:
    """Normalize a batch of raw evidence items with privacy filtering."""
    return [normalize_evidence(item) for item in raw_items]


__all__ = ["normalize_evidence", "normalize_evidence_batch", "privacy_filter_raw_evidence"]
