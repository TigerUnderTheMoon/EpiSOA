"""Main experiment evaluation — soft-match metrics."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.metrics import (
    filter_predictions_to_gold_events,
    opinion_recall,
    semantic_tuple_f1,
    soft_tuple_f1,
    stakeholder_recall,
    support_rate,
    unsupported_rate,
)


def evaluate_main(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    *,
    verifier_enabled: bool = True,
) -> dict[str, float | int | str | None]:
    scored_predictions, excluded_predictions, excluded_event_ids = filter_predictions_to_gold_events(gold, predictions)
    soft = soft_tuple_f1(gold, scored_predictions, threshold=0.5)
    semantic = semantic_tuple_f1(gold, scored_predictions, threshold=0.5)
    metrics: dict[str, float | int | str | None] = {
        "Metric-Scope": "gold_event_scope",
        "Tuple-F1-soft": soft["f1"],
        "Tuple-F1-strict-char@0.5": soft["f1"],
        "Tuple-Precision": soft["precision"],
        "Tuple-Recall": soft["recall"],
        "Tuple-F1-semantic": semantic["f1"],
        "Tuple-Precision-semantic": semantic["precision"],
        "Tuple-Recall-semantic": semantic["recall"],
        "Stakeholder-Recall": stakeholder_recall(gold, scored_predictions),
        "Opinion-Recall": opinion_recall(gold, scored_predictions),
        "Sentiment-Acc": soft["sentiment_accuracy"],
        "Num-Tuples": len(scored_predictions),
        "Num-Tuples-All": len(predictions),
        "Num-Gold": len(gold),
        "Excluded-Predictions": len(excluded_predictions),
        "Excluded-Event-Count": len(excluded_event_ids),
        "Excluded-Event-Ids": "|".join(excluded_event_ids),
    }
    if verifier_enabled:
        metrics["ESR"] = support_rate(scored_predictions)
        metrics["UTR"] = unsupported_rate(scored_predictions)
        metrics["ESR-All"] = support_rate(predictions)
        metrics["UTR-All"] = unsupported_rate(predictions)
    else:
        metrics["ESR"] = None
        metrics["UTR"] = None
        metrics["Candidate-UTR"] = unsupported_rate(scored_predictions)
        metrics["Candidate-UTR-All"] = unsupported_rate(predictions)
    return metrics
