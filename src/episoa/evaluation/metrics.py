"""Paper-facing metric API for EpiSOA experiments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from episoa.evaluation.evaluator import evaluate
from episoa.evaluation.faithfulness_metrics import evaluate_jsonl


PAPER_METRIC_KEYS = [
    "tuple_f1",
    "stakeholder_f1",
    "opinion_f1",
    "sentiment_macro_f1",
    "evidence_recall_at_k",
    "evidence_support_rate",
    "unsupported_tuple_rate",
    "path_recall_at_k",
    "temporal_order_accuracy",
]


def compute_metrics(
    predictions_path: str | Path,
    gold_tuples_path: str | Path,
    gold_event_chains_path: str | Path | None = None,
    *,
    metrics_path: str | Path | None = None,
    k: int = 5,
) -> dict[str, float]:
    """Compute paper-facing metrics and optionally write metrics.json."""
    if gold_event_chains_path is not None and Path(gold_event_chains_path).exists():
        metrics = evaluate(
            predictions_path,
            gold_tuples_path,
            gold_event_chains_path,
            metrics_path=metrics_path,
        )
    else:
        target_path = metrics_path or Path(predictions_path).with_name("metrics.json")
        metrics = evaluate_jsonl(predictions_path, gold_tuples_path, target_path, k=k)
    return ensure_paper_metric_keys(metrics)


def ensure_paper_metric_keys(metrics: dict[str, Any]) -> dict[str, float]:
    """Normalize legacy metric names to the paper-facing metric contract."""
    normalized = {key: float(value) for key, value in metrics.items() if isinstance(value, int | float)}
    if "tuple_f1" not in normalized and "tuple_level_f1" in normalized:
        normalized["tuple_f1"] = normalized["tuple_level_f1"]
    if "sentiment_macro_f1" not in normalized and "sentiment_accuracy" in normalized:
        normalized["sentiment_macro_f1"] = normalized["sentiment_accuracy"]
    if "evidence_support_rate" not in normalized and "support_rate" in normalized:
        normalized["evidence_support_rate"] = normalized["support_rate"]
    if "path_recall_at_k" not in normalized:
        normalized["path_recall_at_k"] = normalized.get("path_recall_at_5", 0.0)
    for key in PAPER_METRIC_KEYS:
        normalized.setdefault(key, 0.0)
    return normalized
