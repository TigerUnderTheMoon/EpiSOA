"""Main experiment evaluation — soft-match metrics."""

from __future__ import annotations

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.metrics import (
    filter_predictions_to_gold_events,
    match_tuples,
    opinion_recall,
    semantic_tuple_f1,
    semantic_tuple_f1_at,
    soft_tuple_f1,
    stakeholder_recall,
    support_rate,
    two_stage_tuple_f1,
    unsupported_rate,
)

STEM_SUFFIXES_TO_NORMALIZE = (
    "及相关征收部门",
    "及联合工作组",
    "及相关职能部门",
    "部门工作人员",
    "及区级工作专班",
    "及属地管理部门",
    "与相关部门",
)

def normalize_stakeholder_for_matching(stakeholder: str) -> str:
    for suffix in STEM_SUFFIXES_TO_NORMALIZE:
        if stakeholder.endswith(suffix):
            return stakeholder[: -len(suffix)]
    return stakeholder


def normalize_for_matching(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
) -> tuple[list[GoldTuple], list[PredictionTuple]]:
    gold_normalized = []
    for g in gold:
        g2 = GoldTuple(
            event_id=g.event_id,
            stakeholder=normalize_stakeholder_for_matching(g.stakeholder),
            opinion=g.opinion,
            sentiment=g.sentiment,
            rationale=g.rationale,
            evidence_ids=g.evidence_ids,
            support_label=g.support_label,
            event_chain_stage=g.event_chain_stage,
            evidence_spans=g.evidence_spans,
            stage_id=g.stage_id,
            stakeholder_id=g.stakeholder_id,
            opinion_id=g.opinion_id,
            annotation_provenance=g.annotation_provenance,
        )
        gold_normalized.append(g2)
    pred_normalized = []
    for p in predictions:
        p2 = PredictionTuple(
            event_id=p.event_id,
            stakeholder=normalize_stakeholder_for_matching(p.stakeholder),
            opinion=p.opinion,
            sentiment=p.sentiment,
            rationale=p.rationale,
            evidence_ids=p.evidence_ids,
            support_label=p.support_label,
            event_chain_stage=p.event_chain_stage,
            evidence_spans=p.evidence_spans,
            stage_id=p.stage_id,
            stakeholder_id=p.stakeholder_id,
            opinion_id=p.opinion_id,
            annotation_provenance=p.annotation_provenance,
            support_score=p.support_score,
            verified=p.verified,
            selection_diagnostics=p.selection_diagnostics,
            verification_diagnosis=p.verification_diagnosis,
            stage_candidate_ids=p.stage_candidate_ids,
            attribution_pass=p.attribution_pass,
        )
        pred_normalized.append(p2)
    return gold_normalized, pred_normalized


def evaluate_main(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    *,
    verifier_enabled: bool = True,
    normalize_stakeholders: bool = True,
) -> dict[str, float | int | str | None]:
    eval_gold, eval_pred = (gold, predictions)
    if normalize_stakeholders:
        eval_gold, eval_pred = normalize_for_matching(gold, predictions)
    scored_predictions, excluded_predictions, excluded_event_ids = filter_predictions_to_gold_events(eval_gold, eval_pred)
    soft = soft_tuple_f1(eval_gold, scored_predictions, threshold=0.5)
    semantic = semantic_tuple_f1(eval_gold, scored_predictions, threshold=0.5)
    metrics: dict[str, float | int | str | None] = {
        "Metric-Scope": "gold_event_scope",
        "Tuple-F1-soft": soft["f1"],
        "Tuple-F1-strict-char@0.5": soft["f1"],
        "Tuple-Precision": soft["precision"],
        "Tuple-Recall": soft["recall"],
        "Tuple-F1-semantic": semantic["f1"],
        "Tuple-Precision-semantic": semantic["precision"],
        "Tuple-Recall-semantic": semantic["recall"],
        "Stakeholder-Recall": stakeholder_recall(eval_gold, scored_predictions),
        "Opinion-Recall": opinion_recall(eval_gold, scored_predictions),
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

    # Two-stage normalized semantic metrics (paper main metric)
    two_stage_03 = two_stage_tuple_f1(eval_gold, eval_pred, normalize=normalize_stakeholders, matcher="semantic", threshold=0.3)
    two_stage_05 = two_stage_tuple_f1(eval_gold, eval_pred, normalize=normalize_stakeholders, matcher="semantic", threshold=0.5)
    metrics["Tuple-F1-semantic@0.3"] = two_stage_03["f1"]
    metrics["Tuple-Precision-semantic@0.3"] = two_stage_03["precision"]
    metrics["Tuple-Recall-semantic@0.3"] = two_stage_03["recall"]
    metrics["Tuple-F1-semantic@0.5"] = two_stage_05["f1"]
    metrics["Tuple-Precision-semantic@0.5"] = two_stage_05["precision"]
    metrics["Tuple-Recall-semantic@0.5"] = two_stage_05["recall"]

    # Stakeholder and opinion recall with semantic matching
    sh_result_sem = match_tuples(
        eval_gold, eval_pred,
        matcher="semantic", threshold=0.3,
        field_weights={"stakeholder": 1.0},
    )
    op_result_sem = match_tuples(
        eval_gold, eval_pred,
        matcher="semantic", threshold=0.3,
        field_weights={"opinion": 1.0},
    )
    metrics["Stakeholder-Recall-semantic@0.3"] = round(len(sh_result_sem["matched_gold_indices"]) / len(eval_gold), 4) if eval_gold else 0.0
    metrics["Opinion-Recall-semantic@0.3"] = round(len(op_result_sem["matched_gold_indices"]) / len(eval_gold), 4) if eval_gold else 0.0
    return metrics
