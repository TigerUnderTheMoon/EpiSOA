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
    gold: list[GoldTuple], predictions: list[PredictionTuple]
) -> dict[str, float]:
    soft = soft_tuple_f1(gold, predictions, threshold=0.5)
    return {
        "Tuple-F1-soft": soft["f1"],
        "Tuple-Precision": soft["precision"],
        "Tuple-Recall": soft["recall"],
        "Stakeholder-Recall": stakeholder_recall(gold, predictions),
        "Sentiment-Acc": soft["sentiment_accuracy"],
        "ESR": support_rate(predictions),
        "UTR": unsupported_rate(predictions),
        "Num-Tuples": len(predictions),
        "Num-Gold": len(gold),
    }
