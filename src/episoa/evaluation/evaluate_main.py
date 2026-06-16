"""Main experiment evaluation — soft-match metrics."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.metrics import (
    filter_predictions_to_gold_events,
    match_tuples,
    opinion_recall,
    semantic_tuple_f1,
    soft_tuple_f1,
    stakeholder_recall,
    support_rate,
    tuple_match_metrics,
    two_stage_tuple_f1,
    unsupported_rate,
)


def evaluate_main(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    *,
    verifier_enabled: bool = True,
    normalize_stakeholders: bool = True,
) -> dict[str, float | int | str | None]:
    scored_predictions, excluded_predictions, excluded_event_ids = filter_predictions_to_gold_events(gold, predictions)
    exact = tuple_match_metrics(gold, scored_predictions, matcher="exact", threshold=1.0)
    soft = soft_tuple_f1(gold, scored_predictions, threshold=0.5)
    semantic_raw_05 = semantic_tuple_f1(gold, scored_predictions, threshold=0.5)
    two_stage_025 = two_stage_tuple_f1(gold, scored_predictions, normalize=normalize_stakeholders, matcher="semantic", threshold=0.25)
    two_stage_03 = two_stage_tuple_f1(gold, scored_predictions, normalize=normalize_stakeholders, matcher="semantic", threshold=0.3)
    two_stage_05 = two_stage_tuple_f1(gold, scored_predictions, normalize=normalize_stakeholders, matcher="semantic", threshold=0.5)
    metrics: dict[str, float | int | str | None] = {
        "Metric-Scope": "gold_event_scope",
        "Tuple-F1-soft": soft["f1"],
        "Tuple-F1-char@0.5": soft["f1"],
        "Tuple-Precision-char@0.5": soft["precision"],
        "Tuple-Recall-char@0.5": soft["recall"],
        "Tuple-F1-exact": exact["f1"],
        "Tuple-Precision-exact": exact["precision"],
        "Tuple-Recall-exact": exact["recall"],
        "Tuple-Precision": soft["precision"],
        "Tuple-Recall": soft["recall"],
        "Tuple-F1-semantic": two_stage_05["f1"],
        "Tuple-Precision-semantic": two_stage_05["precision"],
        "Tuple-Recall-semantic": two_stage_05["recall"],
        "Tuple-F1-semantic-raw@0.5": semantic_raw_05["f1"],
        "Tuple-Precision-semantic-raw@0.5": semantic_raw_05["precision"],
        "Tuple-Recall-semantic-raw@0.5": semantic_raw_05["recall"],
        "Stakeholder-Recall-char@0.5": stakeholder_recall(gold, scored_predictions),
        "Opinion-Recall-char@0.5": opinion_recall(gold, scored_predictions),
        "Sentiment-Acc": two_stage_05["sentiment_accuracy"],
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

    # Two-stage normalized semantic metrics (paper main metric and audits)
    metrics["Tuple-F1-semantic@0.25"] = two_stage_025["f1"]
    metrics["Tuple-Precision-semantic@0.25"] = two_stage_025["precision"]
    metrics["Tuple-Recall-semantic@0.25"] = two_stage_025["recall"]
    metrics["Tuple-F1-semantic@0.3"] = two_stage_03["f1"]
    metrics["Tuple-Precision-semantic@0.3"] = two_stage_03["precision"]
    metrics["Tuple-Recall-semantic@0.3"] = two_stage_03["recall"]
    metrics["Tuple-F1-semantic@0.5"] = two_stage_05["f1"]
    metrics["Tuple-Precision-semantic@0.5"] = two_stage_05["precision"]
    metrics["Tuple-Recall-semantic@0.5"] = two_stage_05["recall"]

    # Stakeholder and opinion recall with semantic matching at each threshold
    sh_result_sem_025 = match_tuples(
        gold, scored_predictions,
        matcher="semantic", threshold=0.25,
        field_weights={"stakeholder": 1.0},
    )
    op_result_sem_025 = match_tuples(
        gold, scored_predictions,
        matcher="semantic", threshold=0.25,
        field_weights={"opinion": 1.0},
    )
    sh_result_sem_03 = match_tuples(
        gold, scored_predictions,
        matcher="semantic", threshold=0.3,
        field_weights={"stakeholder": 1.0},
    )
    op_result_sem_03 = match_tuples(
        gold, scored_predictions,
        matcher="semantic", threshold=0.3,
        field_weights={"opinion": 1.0},
    )
    sh_result_sem_05 = match_tuples(
        gold, scored_predictions,
        matcher="semantic", threshold=0.5,
        field_weights={"stakeholder": 1.0},
    )
    op_result_sem_05 = match_tuples(
        gold, scored_predictions,
        matcher="semantic", threshold=0.5,
        field_weights={"opinion": 1.0},
    )
    metrics["Stakeholder-Recall-semantic@0.25"] = round(len(sh_result_sem_025["matched_gold_indices"]) / len(gold), 4) if gold else 0.0
    metrics["Opinion-Recall-semantic@0.25"] = round(len(op_result_sem_025["matched_gold_indices"]) / len(gold), 4) if gold else 0.0
    metrics["Stakeholder-Recall-semantic@0.3"] = round(len(sh_result_sem_03["matched_gold_indices"]) / len(gold), 4) if gold else 0.0
    metrics["Opinion-Recall-semantic@0.3"] = round(len(op_result_sem_03["matched_gold_indices"]) / len(gold), 4) if gold else 0.0
    metrics["Stakeholder-Recall-semantic@0.5"] = round(len(sh_result_sem_05["matched_gold_indices"]) / len(gold), 4) if gold else 0.0
    metrics["Opinion-Recall-semantic@0.5"] = round(len(op_result_sem_05["matched_gold_indices"]) / len(gold), 4) if gold else 0.0
    metrics["Stakeholder-Recall"] = metrics["Stakeholder-Recall-semantic@0.5"]
    metrics["Opinion-Recall"] = metrics["Opinion-Recall-semantic@0.5"]
    return metrics
