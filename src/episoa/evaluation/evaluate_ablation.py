"""Ablation evaluation."""

from __future__ import annotations

from episoa.evaluation.evaluate_main import evaluate_main


def evaluate_ablation(gold, predictions) -> dict[str, float]:
    return evaluate_main(gold, predictions)
