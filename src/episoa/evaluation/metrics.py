"""Paper metrics for EpiSOA — soft-match and evidence-grounded evaluation."""

from __future__ import annotations

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
    matched_pred_indices: set[int] = set()
    true_positives = 0
    sentiment_correct = 0

    for gt in gold_list:
        best_score = 0.0
        best_pred_idx = -1
        for j, pt in enumerate(pred_list):
            stake_sim = _char_overlap(gt.stakeholder, pt.stakeholder)
            opinion_sim = _char_overlap(gt.opinion, pt.opinion)
            combined = 0.5 * stake_sim + 0.5 * opinion_sim
            if combined > best_score:
                best_score = combined
                best_pred_idx = j

        if best_score >= threshold and best_pred_idx not in matched_pred_indices:
            true_positives += 1
            matched_pred_indices.add(best_pred_idx)
            if gt.sentiment == pred_list[best_pred_idx].sentiment:
                sentiment_correct += 1

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
    """Fraction of gold stakeholders covered by at least one prediction."""
    if not gold:
        return 0.0
    covered = 0
    for gt in gold:
        if any(_char_overlap(gt.stakeholder, pt.stakeholder) >= threshold for pt in predictions):
            covered += 1
    return round(covered / len(gold), 4)


def support_rate(predictions: list[PredictionTuple]) -> float:
    """Fraction of predictions marked as verified (evidence-supported)."""
    return sum(1 for item in predictions if item.verified) / len(predictions) if predictions else 0.0


def unsupported_rate(predictions: list[PredictionTuple]) -> float:
    """Fraction of predictions with unsupported or insufficient_evidence label."""
    unsupported = {"unsupported", "insufficient_evidence"}
    return sum(1 for item in predictions if item.support_label in unsupported) / len(predictions) if predictions else 0.0


def _key(item: GoldTuple | PredictionTuple) -> tuple[str, str, str, str]:
    return (item.event_id, item.stakeholder.lower(), item.opinion.lower(), item.sentiment)
