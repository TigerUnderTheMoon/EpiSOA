"""Event path evaluation metrics."""

from __future__ import annotations

from typing import Any

from episoa.evaluation.tuple_metrics import normalize_text


def path_key(row: dict[str, Any]) -> tuple[str, ...]:
    """Canonical event-chain path key."""
    return tuple(normalize_text(item) for item in row.get("event_chain", []) if normalize_text(item))


def path_recall_at_k(predictions: list[dict[str, Any]], gold: list[dict[str, Any]], k: int = 5) -> float:
    """Recall of gold event chains among top-k predicted chains."""
    gold_paths = {path_key(row) for row in gold if path_key(row)}
    if not gold_paths:
        return 1.0

    predicted_paths: list[tuple[str, ...]] = []
    for row in predictions:
        key = path_key(row)
        if key and key not in predicted_paths:
            predicted_paths.append(key)

    return len(set(predicted_paths[:k]) & gold_paths) / len(gold_paths)


def temporal_order_accuracy(predictions: list[dict[str, Any]], gold: list[dict[str, Any]]) -> float:
    """Share of comparable chains whose event order exactly matches gold order."""
    gold_by_events = {frozenset(path): path for row in gold if (path := path_key(row))}
    if not gold_by_events:
        return 1.0

    comparable = 0
    correct = 0
    for row in predictions:
        predicted = path_key(row)
        if not predicted:
            continue
        gold_path = gold_by_events.get(frozenset(predicted))
        if gold_path is None:
            continue
        comparable += 1
        if predicted == gold_path:
            correct += 1
    if comparable == 0:
        return 0.0
    return correct / comparable


def evaluate_path_metrics(
    predictions: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    k: int = 5,
) -> dict[str, float]:
    return {
        "path_recall_at_1": path_recall_at_k(predictions, gold, k=1),
        "path_recall_at_3": path_recall_at_k(predictions, gold, k=3),
        "path_recall_at_5": path_recall_at_k(predictions, gold, k=5),
        "path_recall_at_k": path_recall_at_k(predictions, gold, k=k),
        "temporal_order_accuracy": temporal_order_accuracy(predictions, gold),
    }
