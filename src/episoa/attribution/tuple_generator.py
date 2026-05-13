"""Generate schema-constrained stakeholder opinion tuples."""

from __future__ import annotations

from episoa.data.schema import EvidenceRecord, PredictionTuple


def generate_tuples(paths: list[dict], evidence: list[EvidenceRecord]) -> list[PredictionTuple]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    predictions: list[PredictionTuple] = []
    for path in paths:
        # EventChainRetriever returns stages with nested evidence items
        for stage in path.get("stages", []):
            for ev_record in stage.get("evidence", []):
                evidence_id = ev_record.get("evidence_id")
                if evidence_id is None:
                    continue
                item = evidence_by_id.get(evidence_id)
                if item is None:
                    continue
                predictions.append(
                    PredictionTuple(
                        event_id=item.event_id,
                        stakeholder=str(item.model_extra.get("stakeholder") or item.platform or item.source or "unknown"),
                        opinion=item.text,
                        sentiment="unknown",
                        rationale="Generated from linked evidence text.",
                        evidence_ids=[item.evidence_id],
                        support_label="supported",
                        support_score=0.5,
                        verified=False,
                    )
                )
    return predictions
