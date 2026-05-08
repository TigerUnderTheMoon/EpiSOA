"""Paper metrics for EpiSOA."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple


def tuple_f1(gold: list[GoldTuple], predictions: list[PredictionTuple]) -> float:
    gold_keys = {_key(item) for item in gold}
    prediction_keys = {_key(item) for item in predictions}
    if not gold_keys or not prediction_keys:
        return 0.0
    tp = len(gold_keys & prediction_keys)
    precision = tp / len(prediction_keys)
    recall = tp / len(gold_keys)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def support_rate(predictions: list[PredictionTuple]) -> float:
    return sum(1 for item in predictions if item.verified) / len(predictions) if predictions else 0.0


def unsupported_rate(predictions: list[PredictionTuple]) -> float:
    unsupported = {"unsupported", "insufficient_evidence"}
    return sum(1 for item in predictions if item.support_label in unsupported) / len(predictions) if predictions else 0.0


def _key(item: GoldTuple | PredictionTuple) -> tuple[str, str, str, str]:
    return (item.event_id, item.stakeholder.lower(), item.opinion.lower(), item.sentiment)
