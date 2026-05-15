"""Paper metrics for EpiSOA — soft-match and evidence-grounded evaluation."""

from __future__ import annotations

from typing import Any

from episoa.data.schema import GoldTuple, PredictionTuple


def _char_overlap(a: str, b: str) -> float:
    """Character-level Jaccard similarity between two strings."""
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def tuple_f1(gold: list[GoldTuple], predictions: list[PredictionTuple]) -> float:
    """Exact-match tuple F1 (strict 4-tuple equality)."""
    gold_keys = {_key(item) for item in gold}
    prediction_keys = {_key(item) for item in predictions}
    if not gold_keys or not prediction_keys:
        return 0.0
    tp = len(gold_keys & prediction_keys)
    precision = tp / len(prediction_keys)
    recall = tp / len(gold_keys)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def soft_tuple_f1(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    threshold: float = 0.5,
) -> dict[str, float]:
    """Soft-match tuple F1 using character Jaccard on stakeholder + opinion.

    For each gold tuple, finds the best-matching prediction.  A match is
    counted when 0.5 * stakeholder_overlap + 0.5 * opinion_overlap >= threshold.

    Returns {precision, recall, f1, true_positives, sentiment_accuracy}.
    """
    if not gold or not predictions:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0,
                "true_positives": 0, "sentiment_accuracy": 0.0}

    gold_list = list(gold)
    pred_list = list(predictions)
    candidate_pairs: list[tuple[float, int, int]] = []

    for gold_idx, gt in enumerate(gold_list):
        gold_event_id = _field(gt, "event_id")
        for pred_idx, pt in enumerate(pred_list):
            if _field(pt, "event_id") != gold_event_id:
                continue
            stake_sim = _char_overlap(_field(gt, "stakeholder"), _field(pt, "stakeholder"))
            opinion_sim = _char_overlap(_field(gt, "opinion"), _field(pt, "opinion"))
            combined = 0.5 * stake_sim + 0.5 * opinion_sim
            if combined >= threshold:
                candidate_pairs.append((combined, gold_idx, pred_idx))

    candidate_pairs.sort(reverse=True, key=lambda item: item[0])
    matched_gold_indices: set[int] = set()
    matched_pred_indices: set[int] = set()
    sentiment_correct = 0

    for _score, gold_idx, pred_idx in candidate_pairs:
        if gold_idx in matched_gold_indices or pred_idx in matched_pred_indices:
            continue
        matched_gold_indices.add(gold_idx)
        matched_pred_indices.add(pred_idx)
        if _field(gold_list[gold_idx], "sentiment") == _field(pred_list[pred_idx], "sentiment"):
            sentiment_correct += 1

    true_positives = len(matched_pred_indices)
    precision = true_positives / len(pred_list)
    recall = true_positives / len(gold_list)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    sentiment_acc = sentiment_correct / true_positives if true_positives > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": true_positives,
        "sentiment_accuracy": round(sentiment_acc, 4),
    }


def stakeholder_recall(
    gold: list[GoldTuple], predictions: list[PredictionTuple], threshold: float = 0.5
) -> float:
    """Fraction of gold stakeholders covered by a same-event prediction."""
    if not gold:
        return 0.0
    candidate_pairs: list[tuple[float, int, int]] = []
    for gold_idx, gt in enumerate(gold):
        gold_event_id = _field(gt, "event_id")
        for pred_idx, pt in enumerate(predictions):
            if _field(pt, "event_id") != gold_event_id:
                continue
            score = _char_overlap(_field(gt, "stakeholder"), _field(pt, "stakeholder"))
            if score >= threshold:
                candidate_pairs.append((score, gold_idx, pred_idx))

    candidate_pairs.sort(reverse=True, key=lambda item: item[0])
    matched_gold_indices: set[int] = set()
    matched_pred_indices: set[int] = set()
    for _score, gold_idx, pred_idx in candidate_pairs:
        if gold_idx in matched_gold_indices or pred_idx in matched_pred_indices:
            continue
        matched_gold_indices.add(gold_idx)
        matched_pred_indices.add(pred_idx)
    return round(len(matched_gold_indices) / len(gold), 4)


def support_rate(predictions: list[PredictionTuple]) -> float:
    """Fraction of predictions marked as verified (evidence-supported)."""
    return sum(1 for item in predictions if item.verified) / len(predictions) if predictions else 0.0


def unsupported_rate(predictions: list[PredictionTuple]) -> float:
    """Fraction of predictions with unsupported or insufficient_evidence label."""
    unsupported = {"unsupported", "insufficient_evidence"}
    return sum(1 for item in predictions if item.support_label in unsupported) / len(predictions) if predictions else 0.0


def _field(item: GoldTuple | PredictionTuple | dict[str, Any], name: str) -> str:
    if isinstance(item, dict):
        return str(item.get(name, ""))
    return str(getattr(item, name))


def _key(item: GoldTuple | PredictionTuple) -> tuple[str, str, str, str]:
    return (
        _field(item, "event_id"),
        _field(item, "stakeholder").lower(),
        _field(item, "opinion").lower(),
        _field(item, "sentiment"),
    )
