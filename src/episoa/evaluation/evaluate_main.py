"""Main experiment evaluation — soft-match metrics."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.metrics import (
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
) -> dict[str, float | None]:
    soft = soft_tuple_f1(gold, predictions, threshold=0.5)
    metrics: dict[str, float | int | None] = {
        "Tuple-F1-soft": soft["f1"],
        "Tuple-Precision": soft["precision"],
        "Tuple-Recall": soft["recall"],
        "Stakeholder-Recall": stakeholder_recall(gold, predictions),
        "Sentiment-Acc": soft["sentiment_accuracy"],
        "Num-Tuples": len(predictions),
        "Num-Gold": len(gold),
    }
    if verifier_enabled:
        metrics["ESR"] = support_rate(predictions)
        metrics["UTR"] = unsupported_rate(predictions)
    else:
        metrics["ESR"] = None
        metrics["UTR"] = None
        metrics["Candidate-UTR"] = unsupported_rate(predictions)
    return metrics
