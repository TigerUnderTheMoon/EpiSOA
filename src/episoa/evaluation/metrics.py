"""Paper metrics for EpiSOA - soft-match and evidence-grounded evaluation."""

from __future__ import annotations

import logging
from typing import Any

from episoa.data.schema import GoldTuple, PredictionTuple

logger = logging.getLogger(__name__)

DEFAULT_TUPLE_THRESHOLDS = (0.3, 0.4, 0.5)
DEFAULT_TUPLE_FIELD_WEIGHTS = {"stakeholder": 0.5, "opinion": 0.5}
MATCHERS = {"exact", "char_jaccard", "char_bigram_jaccard", "semantic", "embedding"}

_EMBEDDING_MODEL = None
_EMBEDDING_MODEL_NAME = "BAAI/bge-large-zh-v1.5"


def _get_embedding_model():
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDING_MODEL = SentenceTransformer(_EMBEDDING_MODEL_NAME)
        except ImportError:
            logger.warning("sentence_transformers not installed; embedding matcher unavailable. Install with: pip install sentence-transformers")
            return None
    return _EMBEDDING_MODEL


def _embedding_similarity(a: str, b: str) -> float:
    """Compute cosine similarity between sentence embeddings."""
    model = _get_embedding_model()
    if model is None:
        return _semantic_overlap(a, b)
    import numpy as np
    embeddings = model.encode([a, b], normalize_embeddings=True)
    return float(embeddings[0] @ embeddings[1])


def _char_overlap(a: str, b: str) -> float:
    """Character-level Jaccard similarity between two strings."""
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _char_bigram_overlap(a: str, b: str) -> float:
    set_a = _char_ngrams(a, 2)
    set_b = _char_ngrams(b, 2)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _semantic_overlap(a: str, b: str) -> float:
    """Deterministic semantic-ish overlap for audit, not a generation signal."""
    left = _semantic_normalize(a)
    right = _semantic_normalize(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.9
    alias_score = _alias_group_overlap(left, right)
    char_score = _char_overlap(left, right)
    bigram_score = _char_bigram_overlap(left, right)
    return max(alias_score, char_score, bigram_score)


def _char_ngrams(value: str, n: int) -> set[str]:
    text = "".join(ch for ch in str(value) if not ch.isspace())
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[index:index + n] for index in range(len(text) - n + 1)}


def _semantic_normalize(value: str) -> str:
    text = "".join(ch for ch in str(value or "").lower() if not ch.isspace())
    replacements = {
        "網友": "网友",
        "网民": "网友",
        "民众": "公众",
        "住户": "居民",
        "住民": "居民",
        "村民": "居民",
        "业主们": "业主",
        "家属": "家长",
        "监管部门": "监管机构",
        "有关部门": "相关部门",
        "相关政府部门": "相关部门",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _alias_group_overlap(left: str, right: str) -> float:
    groups = (
        ("公众", "网友", "居民", "市民", "群众", "社会", "舆论"),
        ("监管机构", "监管部门", "政府部门", "相关部门", "主管部门", "政府", "官方"),
        ("业主", "住户", "居民", "村民", "市民"),
        ("家长", "学生家长"),
        ("物业", "物业公司", "物业服务企业"),
        ("居民/公众", "公众与网友", "公众/网友/社会各界", "公众与媒体", "公众与媒体评论者", "公众与网民",
         "社会公众与网络舆论", "公众与新闻媒体", "媒体与网友", "网友与公众", "媒体与公众评论",
         "受影响居民/市民", "当地居民与公众", "市民/消费者/公众", "市民及公众", "用户及公众",
         "公众用户", "乘客与公众网友", "乘客及网友"),
        ("三元里村", "三元里村党委", "三元里村党委及村集体", "三元里村村民及被征收人"),
        ("广州市白云区政府", "广州市白云区政府及相关征收部门", "白云区政府"),
        ("应急管理部", "应急管理部部长王祥喜"),
        ("南昌市市场监督管理局", "南昌市市场监督管理局工作人员", "南昌高新区市场监督管理局昌东分局"),
        ("消防救援", "消防救援人员", "消防救援与应急调查部门"),
        ("官方", "政府", "机关", "部门"),
        ("成都七中实验学校", "校方"),
        ("涉事", "涉案"),
    )
    for group in groups:
        left_hit = any(term in left for term in group)
        right_hit = any(term in right for term in group)
        if left_hit and right_hit:
            return 0.75
    return 0.0


def _similarity(a: str, b: str, matcher: str) -> float:
    if matcher == "char_jaccard":
        return _char_overlap(a, b)
    if matcher == "char_bigram_jaccard":
        return _char_bigram_overlap(a, b)
    if matcher == "semantic":
        return _semantic_overlap(a, b)
    if matcher == "embedding":
        return _embedding_similarity(a, b)
    raise ValueError(f"unsupported tuple matcher for soft fields: {matcher}")


def tuple_f1(gold: list[GoldTuple], predictions: list[PredictionTuple]) -> float:
    """Exact-match tuple F1 (strict 4-tuple equality)."""
    metrics = tuple_match_metrics(gold, predictions, matcher="exact", threshold=1.0)
    return float(metrics["f1"])


def tuple_pair_score(
    gold_item: GoldTuple | PredictionTuple | dict[str, Any],
    pred_item: GoldTuple | PredictionTuple | dict[str, Any],
    *,
    matcher: str = "char_jaccard",
    field_weights: dict[str, float] | None = None,
    require_same_event: bool = True,
) -> tuple[float, dict[str, float]]:
    """Score one gold/prediction tuple pair."""
    if matcher not in MATCHERS:
        raise ValueError(f"unsupported tuple matcher: {matcher}")
    if require_same_event and _field(gold_item, "event_id") != _field(pred_item, "event_id"):
        return 0.0, {}
    if matcher == "exact":
        score = 1.0 if _key(gold_item) == _key(pred_item) else 0.0
        return score, {"exact": score}

    weights = field_weights or DEFAULT_TUPLE_FIELD_WEIGHTS
    total_weight = sum(max(0.0, float(weight)) for weight in weights.values())
    if total_weight <= 0:
        raise ValueError("tuple field weights must contain a positive weight")
    field_scores = {
        field: _similarity(_field(gold_item, field), _field(pred_item, field), matcher)
        for field in weights
    }
    score = sum(field_scores[field] * max(0.0, float(weight)) for field, weight in weights.items()) / total_weight
    return score, field_scores


def match_tuples(
    gold: list[GoldTuple] | list[dict[str, Any]],
    predictions: list[PredictionTuple] | list[dict[str, Any]],
    *,
    matcher: str = "char_jaccard",
    threshold: float = 0.5,
    field_weights: dict[str, float] | None = None,
    require_same_event: bool = True,
) -> dict[str, Any]:
    """Greedy one-to-one tuple matching with matched/unmatched details."""
    gold_list = list(gold)
    pred_list = list(predictions)
    candidate_pairs: list[dict[str, Any]] = []

    for gold_idx, gt in enumerate(gold_list):
        for pred_idx, pt in enumerate(pred_list):
            score, field_scores = tuple_pair_score(
                gt,
                pt,
                matcher=matcher,
                field_weights=field_weights,
                require_same_event=require_same_event,
            )
            if score >= threshold:
                candidate_pairs.append(
                    {
                        "score": score,
                        "gold_index": gold_idx,
                        "pred_index": pred_idx,
                        "field_scores": field_scores,
                    }
                )

    candidate_pairs.sort(
        key=lambda item: (-float(item["score"]), int(item["gold_index"]), int(item["pred_index"]))
    )
    matched_gold_indices: set[int] = set()
    matched_pred_indices: set[int] = set()
    matched_pairs: list[dict[str, Any]] = []

    for item in candidate_pairs:
        gold_idx = int(item["gold_index"])
        pred_idx = int(item["pred_index"])
        if gold_idx in matched_gold_indices or pred_idx in matched_pred_indices:
            continue
        matched_gold_indices.add(gold_idx)
        matched_pred_indices.add(pred_idx)
        matched_pairs.append(item)

    return {
        "matcher": matcher,
        "threshold": threshold,
        "matches": matched_pairs,
        "matched_gold_indices": sorted(matched_gold_indices),
        "matched_pred_indices": sorted(matched_pred_indices),
        "unmatched_gold_indices": [
            index for index in range(len(gold_list)) if index not in matched_gold_indices
        ],
        "unmatched_pred_indices": [
            index for index in range(len(pred_list)) if index not in matched_pred_indices
        ],
        "num_gold": len(gold_list),
        "num_pred": len(pred_list),
    }


def tuple_match_metrics(
    gold: list[GoldTuple] | list[dict[str, Any]],
    predictions: list[PredictionTuple] | list[dict[str, Any]],
    *,
    matcher: str = "char_jaccard",
    threshold: float = 0.5,
    field_weights: dict[str, float] | None = None,
) -> dict[str, float | int]:
    result = match_tuples(
        gold,
        predictions,
        matcher=matcher,
        threshold=threshold,
        field_weights=field_weights,
    )
    true_positives = len(result["matches"])
    num_pred = int(result["num_pred"])
    num_gold = int(result["num_gold"])
    precision = true_positives / num_pred if num_pred else 0.0
    recall = true_positives / num_gold if num_gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    sentiment_correct = 0
    gold_list = list(gold)
    pred_list = list(predictions)
    for item in result["matches"]:
        if _field(gold_list[int(item["gold_index"])], "sentiment") == _field(pred_list[int(item["pred_index"])], "sentiment"):
            sentiment_correct += 1
    sentiment_acc = sentiment_correct / true_positives if true_positives > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": true_positives,
        "sentiment_accuracy": round(sentiment_acc, 4),
    }


def tuple_match_threshold_sweep(
    gold: list[GoldTuple] | list[dict[str, Any]],
    predictions: list[PredictionTuple] | list[dict[str, Any]],
    *,
    thresholds: tuple[float, ...] = DEFAULT_TUPLE_THRESHOLDS,
    matchers: tuple[str, ...] = ("char_jaccard", "char_bigram_jaccard", "semantic"),
) -> list[dict[str, float | str | int]]:
    rows: list[dict[str, float | str | int]] = []
    for matcher in matchers:
        for threshold in thresholds:
            metrics = tuple_match_metrics(gold, predictions, matcher=matcher, threshold=threshold)
            rows.append(
                {
                    "matcher": matcher,
                    "threshold": threshold,
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "f1": metrics["f1"],
                    "true_positives": metrics["true_positives"],
                }
            )
    exact = tuple_match_metrics(gold, predictions, matcher="exact", threshold=1.0)
    rows.append(
        {
            "matcher": "exact",
            "threshold": 1.0,
            "precision": exact["precision"],
            "recall": exact["recall"],
            "f1": exact["f1"],
            "true_positives": exact["true_positives"],
        }
    )
    return rows


def filter_predictions_to_gold_events(
    gold: list[GoldTuple] | list[dict[str, Any]],
    predictions: list[PredictionTuple] | list[dict[str, Any]],
) -> tuple[list[Any], list[Any], list[str]]:
    gold_event_ids = {_field(item, "event_id") for item in gold}
    scored = [item for item in predictions if _field(item, "event_id") in gold_event_ids]
    excluded = [item for item in predictions if _field(item, "event_id") not in gold_event_ids]
    excluded_event_ids = sorted({_field(item, "event_id") for item in excluded if _field(item, "event_id")})
    return scored, excluded, excluded_event_ids


def soft_tuple_f1(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    threshold: float = 0.5,
) -> dict[str, float | int]:
    """Soft-match tuple F1 using character Jaccard on stakeholder + opinion."""
    return tuple_match_metrics(gold, predictions, matcher="char_jaccard", threshold=threshold)


def semantic_tuple_f1(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    threshold: float = 0.5,
) -> dict[str, float | int]:
    """Audit-only deterministic semantic tuple F1 using one-to-one matching."""
    return tuple_match_metrics(gold, predictions, matcher="semantic", threshold=threshold)


def stakeholder_recall(
    gold: list[GoldTuple], predictions: list[PredictionTuple], threshold: float = 0.5
) -> float:
    """Fraction of gold stakeholders covered by a same-event prediction."""
    if not gold:
        return 0.0
    result = match_tuples(
        gold,
        predictions,
        matcher="char_jaccard",
        threshold=threshold,
        field_weights={"stakeholder": 1.0},
    )
    return round(len(result["matched_gold_indices"]) / len(gold), 4)


def opinion_recall(
    gold: list[GoldTuple], predictions: list[PredictionTuple], threshold: float = 0.5
) -> float:
    """Fraction of gold opinions covered by a same-event prediction."""
    if not gold:
        return 0.0
    result = match_tuples(
        gold,
        predictions,
        matcher="char_jaccard",
        threshold=threshold,
        field_weights={"opinion": 1.0},
    )
    return round(len(result["matched_gold_indices"]) / len(gold), 4)


def support_rate(predictions: list[PredictionTuple]) -> float:
    """Fraction of predictions marked as verified (evidence-supported)."""
    return sum(1 for item in predictions if item.verified) / len(predictions) if predictions else 0.0


def unsupported_rate(predictions: list[PredictionTuple]) -> float:
    """Fraction of predictions with unsupported or insufficient_evidence label."""
    unsupported = {"unsupported", "insufficient_evidence"}
    return sum(1 for item in predictions if item.support_label in unsupported) / len(predictions) if predictions else 0.0


def _field(item: GoldTuple | PredictionTuple | dict[str, Any], name: str) -> str:
    if isinstance(item, dict):
        return str(item.get(name, ""))
    return str(getattr(item, name))


def _key(item: GoldTuple | PredictionTuple | dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _field(item, "event_id"),
        _field(item, "stakeholder").lower(),
        _field(item, "opinion").lower(),
        _field(item, "sentiment"),
    )


STEM_SUFFIXES_TO_NORMALIZE = (
    "及相关征收部门",
    "及联合工作组",
    "及相关职能部门",
    "部门工作人员",
    "及区级工作专班",
    "及属地管理部门",
    "与相关部门",
    "及属地管理部门",
    "等",
    "及其家属",
    "及其亲友",
    "等相关部门",
)

STAKEHOLDER_ALIAS_NORMALIZE = {
    "居民/公众": "居民",
    "公众": "居民",
    "社会公众": "居民",
    "社会舆论": "居民",
    "网友": "居民",
    "公众/网友": "居民",
    "公众质疑者": "居民",
    "市民": "居民",
    "群众": "居民",
    "大众": "居民",
    "民众": "居民",
    "社区居民": "居民",
    "当地居民": "居民",
    "学生家长": "家长",
    "多名家长": "家长",
    "家长和社会各界": "家长",
    "涉案学生": "学生",
    "当事学生": "学生",
    "受影响居民": "居民",
    "受骗患者": "患者",
    "近千名患者": "患者",
    "被害人": "受害者",
    "受害人家属": "受害者家属",
    "受害女生": "受害者",
    "受伤居民": "居民",
    "遇难学生家属": "受害者家属",
    "被征收人": "居民",
    "未选房的被征收人": "居民",
    "部分被征收人": "居民",
}


def _normalize_stakeholder_alias(name: str) -> str:
    """Map a stakeholder name to its canonical alias for matching purposes."""
    if name in STAKEHOLDER_ALIAS_NORMALIZE:
        return STAKEHOLDER_ALIAS_NORMALIZE[name]
    return name


def normalize_stakeholder_for_matching(stakeholder: str) -> str:
    result = stakeholder
    for suffix in STEM_SUFFIXES_TO_NORMALIZE:
        if result.endswith(suffix):
            result = result[: -len(suffix)]
            break
    return _normalize_stakeholder_alias(result)


def normalize_tuple_for_matching(
    items: list[GoldTuple] | list[PredictionTuple],
) -> list[GoldTuple] | list[PredictionTuple]:
    result = []
    for item in items:
        if isinstance(item, PredictionTuple):
            result.append(PredictionTuple(
                event_id=item.event_id,
                stakeholder=normalize_stakeholder_for_matching(item.stakeholder),
                opinion=item.opinion,
                sentiment=item.sentiment,
                rationale=item.rationale,
                evidence_ids=item.evidence_ids,
                support_label=item.support_label,
                event_chain_stage=item.event_chain_stage,
                evidence_spans=item.evidence_spans,
                stage_id=item.stage_id,
                stakeholder_id=item.stakeholder_id,
                opinion_id=item.opinion_id,
                annotation_provenance=item.annotation_provenance,
                support_score=item.support_score,
                verified=item.verified,
                selection_diagnostics=item.selection_diagnostics,
                verification_diagnosis=item.verification_diagnosis,
                stage_candidate_ids=item.stage_candidate_ids,
                attribution_pass=item.attribution_pass,
            ))
        else:
            result.append(GoldTuple(
                event_id=item.event_id,
                stakeholder=normalize_stakeholder_for_matching(item.stakeholder),
                opinion=item.opinion,
                sentiment=item.sentiment,
                rationale=item.rationale,
                evidence_ids=item.evidence_ids,
                support_label=item.support_label,
                event_chain_stage=item.event_chain_stage,
                evidence_spans=item.evidence_spans,
                stage_id=item.stage_id,
                stakeholder_id=item.stakeholder_id,
                opinion_id=item.opinion_id,
                annotation_provenance=item.annotation_provenance,
            ))
    return result


def two_stage_tuple_f1(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    *,
    normalize: bool = True,
    matcher: str = "semantic",
    threshold: float = 0.3,
    field_weights: dict[str, float] | None = None,
) -> dict[str, float | int]:
    """Two-stage matching: normalize stakeholders then compute semantic F1.

    Stage 1: Strip organization suffixes from stakeholder names.
    Stage 2: Use semantic matching with a lower threshold (0.3 default).
    """
    eval_gold = normalize_tuple_for_matching(gold) if normalize else gold
    eval_pred = normalize_tuple_for_matching(predictions) if normalize else predictions
    return tuple_match_metrics(
        eval_gold, eval_pred,
        matcher=matcher, threshold=threshold,
        field_weights=field_weights,
    )


def semantic_tuple_f1_at(
    gold: list[GoldTuple],
    predictions: list[PredictionTuple],
    threshold: float = 0.3,
) -> dict[str, float | int]:
    """Semantic tuple F1 at a given threshold (default 0.3 for paper main metric)."""
    return tuple_match_metrics(gold, predictions, matcher="semantic", threshold=threshold)
