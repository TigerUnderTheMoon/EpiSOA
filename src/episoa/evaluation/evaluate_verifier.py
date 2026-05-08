"""Verifier evaluation."""

from __future__ import annotations

from episoa.data.schema import PredictionTuple
from episoa.evaluation.metrics import support_rate, unsupported_rate


def evaluate_verifier(predictions: list[PredictionTuple]) -> dict[str, float]:
    return {"ESR": support_rate(predictions), "UTR": unsupported_rate(predictions)}
