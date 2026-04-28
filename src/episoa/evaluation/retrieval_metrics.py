"""Evidence retrieval evaluation metrics."""

from __future__ import annotations

from typing import Any


def evidence_ids(row: dict[str, Any]) -> list[str]:
    """Extract evidence IDs from gold or prediction rows."""
    if "evidence_ids" in row:
        return [str(item) for item in row.get("evidence_ids", [])]

    ids: list[str] = []
    for item in row.get("evidence", []) or []:
        if isinstance(item, dict) and item.get("evidence_id"):
            ids.append(str(item["evidence_id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def evidence_recall_at_k(predictions: list[dict[str, Any]], gold: list[dict[str, Any]], k: int = 5) -> float:
    """Recall of gold evidence IDs among predicted evidence IDs at k."""
    gold_ids = {evidence_id for row in gold for evidence_id in evidence_ids(row)}
    if not gold_ids:
        return 1.0

    predicted_ids: list[str] = []
    for row in predictions:
        for evidence_id in evidence_ids(row):
            if evidence_id not in predicted_ids:
                predicted_ids.append(evidence_id)

    return len(set(predicted_ids[:k]) & gold_ids) / len(gold_ids)


def evaluate_retrieval_metrics(
    predictions: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    k: int = 5,
) -> dict[str, float]:
    return {
        "evidence_recall_at_1": evidence_recall_at_k(predictions, gold, k=1),
        "evidence_recall_at_3": evidence_recall_at_k(predictions, gold, k=3),
        "evidence_recall_at_5": evidence_recall_at_k(predictions, gold, k=5),
        "evidence_recall_at_k": evidence_recall_at_k(predictions, gold, k=k),
    }
