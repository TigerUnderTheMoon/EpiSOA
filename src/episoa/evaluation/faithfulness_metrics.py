"""Faithfulness evaluation metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from episoa.evaluation.path_metrics import evaluate_path_metrics
from episoa.evaluation.retrieval_metrics import evaluate_retrieval_metrics
from episoa.evaluation.tuple_metrics import (
    evaluate_tuple_metrics,
    load_jsonl,
    write_metrics_json,
)


def unsupported_tuple_rate(predictions: list[dict[str, Any]], gold: list[dict[str, Any]] | None = None) -> float:
    """Fraction of predicted tuples that are unsupported.

    A tuple is considered unsupported when `verified` is false, `support_score`
    is below 0.75, or no evidence IDs/objects are attached.
    """
    if not predictions:
        return 0.0

    unsupported = 0
    for row in predictions:
        support_score = float(row.get("support_score", 0.0) or 0.0)
        verified = bool(row.get("verified", False))
        evidence = row.get("evidence") or row.get("evidence_ids") or []
        if not verified or support_score < 0.75 or not evidence:
            unsupported += 1

    return unsupported / len(predictions)


def support_rate(predictions: list[dict[str, Any]], gold: list[dict[str, Any]] | None = None) -> float:
    """Fraction of predicted tuples that are supported."""
    if not predictions:
        return 0.0
    return 1.0 - unsupported_tuple_rate(predictions, gold)


def evaluate_faithfulness_metrics(
    predictions: list[dict[str, Any]],
    gold: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    evidence_support = support_rate(predictions, gold)
    return {
        "evidence_support_rate": evidence_support,
        "support_rate": evidence_support,
        "unsupported_tuple_rate": unsupported_tuple_rate(predictions, gold),
    }


def evaluate_jsonl(
    prediction_jsonl: str | Path,
    gold_jsonl: str | Path,
    metrics_json: str | Path,
    *,
    k: int = 5,
) -> dict[str, float]:
    """Evaluate prediction JSONL against gold JSONL and write metrics JSON."""
    predictions = load_jsonl(prediction_jsonl)
    gold = load_jsonl(gold_jsonl)

    metrics: dict[str, float] = {}
    metrics.update(evaluate_tuple_metrics(predictions, gold))
    metrics.update(evaluate_retrieval_metrics(predictions, gold, k=k))
    metrics.update(evaluate_path_metrics(predictions, gold, k=k))
    metrics.update(evaluate_faithfulness_metrics(predictions, gold))

    write_metrics_json(metrics, metrics_json)
    return metrics
