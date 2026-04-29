"""Tuple-level evaluation metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSONL file into dictionaries."""
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_metrics_json(metrics: dict[str, float], path: str | Path) -> None:
    """Write metrics as pretty JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def tuple_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Canonical tuple key for tuple-level matching."""
    return (
        normalize_text(row.get("event")),
        normalize_text(row.get("stakeholder")),
        normalize_text(row.get("opinion")),
        normalize_text(row.get("sentiment")),
    )


def stakeholder_key(row: dict[str, Any]) -> str:
    return normalize_text(row.get("stakeholder"))


def opinion_key(row: dict[str, Any]) -> str:
    return normalize_text(row.get("opinion"))


def precision_from_sets(predicted: set[Any], gold: set[Any]) -> float:
    """Compute exact-match set precision."""
    if not predicted and not gold:
        return 1.0
    if not predicted:
        return 0.0
    true_positive = len(predicted & gold)
    return true_positive / len(predicted)


def recall_from_sets(predicted: set[Any], gold: set[Any]) -> float:
    """Compute exact-match set recall."""
    if not predicted and not gold:
        return 1.0
    if not gold:
        return 1.0
    true_positive = len(predicted & gold)
    return true_positive / len(gold)


def f1_from_sets(predicted: set[Any], gold: set[Any]) -> float:
    """Compute exact-match set F1."""
    precision = precision_from_sets(predicted, gold)
    recall = recall_from_sets(predicted, gold)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def stakeholder_precision(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """Precision over unique stakeholders."""
    return precision_from_sets(
        {stakeholder_key(row) for row in predictions if stakeholder_key(row)},
        {stakeholder_key(row) for row in gold if stakeholder_key(row)},
    )


def stakeholder_recall(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """Recall over unique stakeholders."""
    return recall_from_sets(
        {stakeholder_key(row) for row in predictions if stakeholder_key(row)},
        {stakeholder_key(row) for row in gold if stakeholder_key(row)},
    )


def stakeholder_f1(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """F1 over unique stakeholders."""
    return f1_from_sets(
        {stakeholder_key(row) for row in predictions if stakeholder_key(row)},
        {stakeholder_key(row) for row in gold if stakeholder_key(row)},
    )


def opinion_f1(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """F1 over unique normalized opinion strings."""
    return f1_from_sets(
        {opinion_key(row) for row in predictions if opinion_key(row)},
        {opinion_key(row) for row in gold if opinion_key(row)},
    )


def tuple_level_f1(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """Exact-match F1 over event/stakeholder/opinion/sentiment tuples."""
    return f1_from_sets(
        {tuple_key(row) for row in predictions if any(tuple_key(row))},
        {tuple_key(row) for row in gold if any(tuple_key(row))},
    )


def sentiment_accuracy(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """Accuracy of sentiment on matched event/stakeholder/opinion triples."""
    gold_by_claim = {
        (
            normalize_text(row.get("event")),
            normalize_text(row.get("stakeholder")),
            normalize_text(row.get("opinion")),
        ): normalize_text(row.get("sentiment"))
        for row in gold
    }
    comparable = 0
    correct = 0
    for row in predictions:
        claim = (
            normalize_text(row.get("event")),
            normalize_text(row.get("stakeholder")),
            normalize_text(row.get("opinion")),
        )
        if claim not in gold_by_claim:
            continue
        comparable += 1
        if normalize_text(row.get("sentiment")) == gold_by_claim[claim]:
            correct += 1
    if comparable == 0:
        return 0.0 if gold_by_claim else 1.0
    return correct / comparable


def evaluate_tuple_metrics(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> dict[str, float]:
    """Compute all tuple-level metrics."""
    tuple_f1 = tuple_level_f1(predictions, gold)
    sentiment_f1 = sentiment_accuracy(predictions, gold)
    return {
        "stakeholder_precision": stakeholder_precision(predictions, gold),
        "stakeholder_recall": stakeholder_recall(predictions, gold),
        "stakeholder_f1": stakeholder_f1(predictions, gold),
        "opinion_f1": opinion_f1(predictions, gold),
        "sentiment_accuracy": sentiment_f1,
        "sentiment_macro_f1": sentiment_f1,
        "tuple_f1": tuple_f1,
        "tuple_level_f1": tuple_f1,
    }
