"""Faithfulness verifier for generated SOA tuples."""

from __future__ import annotations

from episoa.data.schema import EvidenceRecord, PredictionTuple


def verify_tuples(predictions: list[PredictionTuple], evidence: list[EvidenceRecord], threshold: float = 0.75) -> list[PredictionTuple]:
    evidence_ids = {item.evidence_id for item in evidence}
    verified: list[PredictionTuple] = []
    for prediction in predictions:
        support = all(evidence_id in evidence_ids for evidence_id in prediction.evidence_ids)
        score = 1.0 if support else 0.0
        verified.append(
            prediction.model_copy(
                update={
                    "support_score": score,
                    "verified": score >= threshold,
                    "support_label": "supported" if score >= threshold else "insufficient_evidence",
                }
            )
        )
    return verified
