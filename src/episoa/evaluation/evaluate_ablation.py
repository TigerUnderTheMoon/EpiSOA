"""Ablation evaluation — soft-match metrics plus ablation-specific comparisons."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.evaluate_main import evaluate_main


def evaluate_ablation(
    gold: list[GoldTuple], predictions: list[PredictionTuple]
) -> dict[str, float]:
    """Evaluate one ablation setting against gold.

    Uses soft-match tuple F1 so that different ablation settings produce
    differentiated scores (unlike exact-match which is always ~0).
    """
    return evaluate_main(gold, predictions)
