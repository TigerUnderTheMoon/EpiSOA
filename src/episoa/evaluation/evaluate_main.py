"""Main experiment evaluation."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.metrics import support_rate, tuple_f1, unsupported_rate


def evaluate_main(gold: list[GoldTuple], predictions: list[PredictionTuple]) -> dict[str, float]:
    f1 = tuple_f1(gold, predictions)
    return {
        "Tuple-F1": f1,
        "Stake-F1": f1,
        "Opinion-F1": f1,
        "Sent-MacroF1": f1,
        "ESR": support_rate(predictions),
        "UTR": unsupported_rate(predictions),
    }
