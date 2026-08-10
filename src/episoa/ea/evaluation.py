"""Shared M4 evaluation schema, normalization, matching, and metrics."""

from __future__ import annotations

from collections import Counter
from typing import Literal, get_args

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from episoa.ea.matching import SemanticEquivalenceRules, match_explanation
from episoa.ea.schema import (
    EMOTION_VALUES,
    RELATION_BY_EFFECT_TYPE,
    STANCE_VALUES,
    EffectType,
    RelationEvaluationLabel,
    RelationType,
    StakeholderCategory,
)
from episoa.ea.schema import EvidenceLink as EAEvidenceLink

MethodId = Literal[
    "long_context_event_llm",
    "long_context_event_llm_evidence",
    "direct_pair_classification",
    "original_episoa",
    "episoa_ea",
]

METHOD_IDS = (
    "long_context_event_llm",
    "long_context_event_llm_evidence",
    "direct_pair_classification",
    "original_episoa",
    "episoa_ea",
)
RELATION_LABELS = (
    "stance_rationale",
    "emotion_trigger",
    "action_motivation",
    "no_relation",
)
STANCE_LABELS = ("support", "oppose", "question", "neutral", "uncertain")
EMOTION_LABELS = ("positive", "negative", "neutral", "uncertain")
NORMALIZATION_VERSION = "ea-normalization-v1.5"
EVALUATOR_VERSION = "ea-evaluator-v1.5"


class EvaluationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationEffect(EvaluationBase):
    effect_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    stakeholder_category: StakeholderCategory
    effect_type: EffectType
    effect_value: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_value(self) -> EvaluationEffect:
        if self.effect_type == "stance" and self.effect_value not in STANCE_VALUES:
            raise ValueError("invalid stance value")
        if self.effect_type == "emotion" and self.effect_value not in EMOTION_VALUES:
            raise ValueError("invalid emotion value")
        return self


class EvaluationClaim(EvaluationBase):
    claim_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    stakeholder_category: StakeholderCategory
    effect_type: EffectType
    effect_value: str = Field(..., min_length=1)
    relation_type: RelationType
    attribution_holder_category: StakeholderCategory | None = None
    explanation: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_value(self) -> EvaluationClaim:
        if self.effect_type == "stance" and self.effect_value not in STANCE_VALUES:
            raise ValueError("invalid stance value")
        if self.effect_type == "emotion" and self.effect_value not in EMOTION_VALUES:
            raise ValueError("invalid emotion value")
        expected_relation = RELATION_BY_EFFECT_TYPE[self.effect_type]
        if self.relation_type != expected_relation:
            raise ValueError(
                f"{self.effect_type} Claim requires relation_type={expected_relation}"
            )
        return self


class EvaluationEvidenceSpan(EvaluationBase):
    target_type: Literal["effect", "claim"]
    target_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    support_field: str = Field(..., min_length=1)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., gt=0)
    span_text: str = Field(..., min_length=1)
    support_label: Literal["supports", "contradicts", "insufficient"] = "supports"

    @model_validator(mode="after")
    def validate_offsets(self) -> EvaluationEvidenceSpan:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class RelationDecisionItem(EvaluationBase):
    candidate_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    label: RelationEvaluationLabel


class VerificationDecisionItem(EvaluationBase):
    candidate_id: str = Field(..., min_length=1)
    gold_accept: bool
    predicted_status: Literal["verified", "insufficient", "rejected"]


class EvaluationBundle(EvaluationBase):
    method_id: MethodId
    document_ids: list[str]
    effects: list[EvaluationEffect] = Field(default_factory=list)
    claims: list[EvaluationClaim] = Field(default_factory=list)
    evidence_spans: list[EvaluationEvidenceSpan] = Field(default_factory=list)
    relation_decisions: list[RelationDecisionItem] = Field(default_factory=list)
    verification_decisions: list[VerificationDecisionItem] = Field(default_factory=list)
    normalization_version: str = NORMALIZATION_VERSION

    @model_validator(mode="after")
    def validate_document_set(self) -> EvaluationBundle:
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("evaluation Document input set contains duplicates")
        return self


class GoldEvaluationDataset(EvaluationBase):
    dataset_version: str = Field(..., min_length=1)
    document_ids: list[str]
    effects: list[EvaluationEffect] = Field(default_factory=list)
    claims: list[EvaluationClaim] = Field(default_factory=list)
    evidence_spans: list[EvaluationEvidenceSpan] = Field(default_factory=list)
    relation_decisions: list[RelationDecisionItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_gold_claim_holders(self) -> GoldEvaluationDataset:
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("Gold Document input set contains duplicates")
        if any(row.attribution_holder_category is None for row in self.claims):
            raise ValueError("Gold claims require attribution_holder_category")
        return self


STAKEHOLDER_ALIASES: dict[str, str] = {
    "政府": "government",
    "有关部门": "government",
    "政府部门": "government",
    "事业单位": "public_institution",
    "学校": "public_institution",
    "医院": "public_institution",
    "企业": "enterprise",
    "开发商": "enterprise",
    "物业": "enterprise",
    "居民": "affected_public",
    "业主": "affected_public",
    "业主代表": "affected_public",
    "家长": "affected_public",
    "社会组织": "social_organization",
    "业委会": "social_organization",
    "专家": "expert",
    "媒体": "media",
    "公众": "general_public",
    "网民": "general_public",
    "未知": "other_or_unknown",
}
STANCE_ALIASES = {
    "支持": "support",
    "赞同": "support",
    "接受": "support",
    "反对": "oppose",
    "不同意": "oppose",
    "不接受": "oppose",
    "质疑": "question",
    "中立": "neutral",
    "无法判断": "uncertain",
}
EMOTION_ALIASES = {
    "满意": "positive",
    "欣慰": "positive",
    "不满": "negative",
    "担忧": "negative",
    "愤怒": "negative",
    "平静": "neutral",
    "无法判断": "uncertain",
}


def normalize_stakeholder_category(value: str) -> str:
    text = str(value or "").strip()
    if text in STAKEHOLDER_ALIASES:
        return STAKEHOLDER_ALIASES[text]
    if text in get_args(StakeholderCategory):
        return text
    raise ValueError(f"unknown stakeholder category: {value}")


def normalize_effect_value(effect_type: str, value: str) -> str:
    text = str(value or "").strip()
    if effect_type == "stance":
        normalized = STANCE_ALIASES.get(text, text)
        if normalized not in STANCE_VALUES:
            raise ValueError(f"unknown stance value: {value}")
        return normalized
    if effect_type == "emotion":
        normalized = EMOTION_ALIASES.get(text, text)
        if normalized not in EMOTION_VALUES:
            raise ValueError(f"unknown emotion value: {value}")
        return normalized
    if effect_type == "action" and text:
        return text
    raise ValueError(f"invalid Effect Type/value: {effect_type}/{value}")


def adapt_method_output(
    method_id: MethodId,
    *,
    document_ids: list[str],
    raw: dict,
) -> EvaluationBundle:
    """Apply the same frozen normalization path to every method."""
    effects = []
    effect_by_id: dict[str, EvaluationEffect] = {}
    for row in raw.get("effects", []):
        payload = dict(row)
        payload["stakeholder_category"] = normalize_stakeholder_category(
            payload["stakeholder_category"]
        )
        payload["effect_value"] = normalize_effect_value(
            payload["effect_type"], payload["effect_value"]
        )
        effect = EvaluationEffect.model_validate(payload)
        effects.append(effect)
        effect_by_id[effect.effect_id] = effect

    claims = []
    for row in raw.get("claims", []):
        payload = dict(row)
        if "stakeholder_category" not in payload and payload.get("effect_id"):
            effect = effect_by_id.get(str(payload["effect_id"]))
            if effect is None:
                raise ValueError("Claim references an unknown evaluation Effect")
            payload["stakeholder_category"] = effect.stakeholder_category
            payload["effect_type"] = effect.effect_type
            payload["effect_value"] = effect.effect_value
        payload["stakeholder_category"] = normalize_stakeholder_category(
            payload["stakeholder_category"]
        )
        holder = payload.get("attribution_holder_category")
        if holder not in (None, ""):
            payload["attribution_holder_category"] = normalize_stakeholder_category(
                holder
            )
        else:
            payload["attribution_holder_category"] = None
        payload["effect_value"] = normalize_effect_value(
            payload["effect_type"], payload["effect_value"]
        )
        payload.pop("effect_id", None)
        claims.append(EvaluationClaim.model_validate(payload))

    return EvaluationBundle(
        method_id=method_id,
        document_ids=list(document_ids),
        effects=effects,
        claims=claims,
        evidence_spans=[
            EvaluationEvidenceSpan.model_validate(row)
            for row in raw.get("evidence_spans", [])
        ],
        relation_decisions=[
            RelationDecisionItem.model_validate(row)
            for row in raw.get("relation_decisions", [])
        ],
        verification_decisions=[
            VerificationDecisionItem.model_validate(row)
            for row in raw.get("verification_decisions", [])
        ],
    )


def evaluate_method(
    gold: GoldEvaluationDataset,
    prediction: EvaluationBundle,
    *,
    semantic_rules: SemanticEquivalenceRules,
    explanation_span_threshold: float = 0.5,
) -> dict:
    if set(prediction.document_ids) != set(gold.document_ids):
        raise ValueError("all methods must use the same Document input set as Gold")
    if prediction.normalization_version != NORMALIZATION_VERSION:
        raise ValueError("all methods must use the frozen shared normalizer")
    claim_result = attribution_claim_metrics(
        gold.claims,
        prediction.claims,
        gold.evidence_spans,
        prediction.evidence_spans,
        rules=semantic_rules,
        span_threshold=explanation_span_threshold,
    )
    holder_matches = _match_claims(
        gold.claims,
        prediction.claims,
        gold.evidence_spans,
        prediction.evidence_spans,
        rules=semantic_rules,
        span_threshold=explanation_span_threshold,
        require_holder=False,
    )
    return {
        "method_id": prediction.method_id,
        "normalization_version": NORMALIZATION_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "stakeholder_category_f1": stakeholder_category_f1(
            gold.effects, prediction.effects
        ),
        "stance_macro_f1": effect_value_macro_f1(
            gold.effects,
            prediction.effects,
            effect_type="stance",
            labels=STANCE_LABELS,
        ),
        "emotion_macro_f1": effect_value_macro_f1(
            gold.effects,
            prediction.effects,
            effect_type="emotion",
            labels=EMOTION_LABELS,
        ),
        "relation_decision_macro_f1": relation_decision_macro_f1(
            gold.relation_decisions, prediction.relation_decisions
        ),
        "attribution_claim": claim_result,
        "attribution_holder_category_accuracy": attribution_holder_accuracy(
            gold.claims, prediction.claims, holder_matches
        ),
        "holder_category_mismatch_rate": holder_category_mismatch_rate(
            gold.claims, prediction.claims, holder_matches
        ),
        "evidence_span_character_f1": evidence_span_character_f1(
            gold.evidence_spans, prediction.evidence_spans
        ),
        "unsupported_claim_rate": unsupported_claim_rate(
            prediction.claims, prediction.evidence_spans
        ),
        "verification_errors": verification_error_rates(
            prediction.verification_decisions
        ),
    }


def stakeholder_category_f1(
    gold: list[EvaluationEffect], prediction: list[EvaluationEffect]
) -> dict[str, float | int]:
    gold_items = Counter((row.document_id, row.stakeholder_category) for row in gold)
    pred_items = Counter(
        (row.document_id, row.stakeholder_category) for row in prediction
    )
    return _counter_prf(gold_items, pred_items)


def effect_value_macro_f1(
    gold: list[EvaluationEffect],
    prediction: list[EvaluationEffect],
    *,
    effect_type: str,
    labels: tuple[str, ...],
) -> dict:
    per_label = {}
    for label in labels:
        gold_items = Counter(
            (
                row.document_id,
                row.stakeholder_category,
                _normalize_text(row.target),
                row.effect_value,
            )
            for row in gold
            if row.effect_type == effect_type and row.effect_value == label
        )
        pred_items = Counter(
            (
                row.document_id,
                row.stakeholder_category,
                _normalize_text(row.target),
                row.effect_value,
            )
            for row in prediction
            if row.effect_type == effect_type and row.effect_value == label
        )
        per_label[label] = _counter_prf(gold_items, pred_items)
    return {
        "macro_f1": round(
            sum(float(row["f1"]) for row in per_label.values()) / len(labels), 6
        ),
        "per_label": per_label,
    }


def relation_decision_macro_f1(
    gold: list[RelationDecisionItem], prediction: list[RelationDecisionItem]
) -> dict:
    gold_by_id = _unique_by_id(gold, "candidate_id", "Gold relation candidates")
    pred_by_id = _unique_by_id(
        prediction, "candidate_id", "prediction relation candidates"
    )
    extra = sorted(set(pred_by_id) - set(gold_by_id))
    if extra:
        raise ValueError(
            "Relation Decision Macro-F1 requires the fixed Gold candidate set; "
            f"unknown predictions: {extra}"
        )
    document_mismatches = sorted(
        candidate_id
        for candidate_id, prediction_row in pred_by_id.items()
        if prediction_row.document_id != gold_by_id[candidate_id].document_id
    )
    if document_mismatches:
        raise ValueError(
            "Relation Decision predictions changed Gold document provenance: "
            f"{document_mismatches}"
        )
    per_label = {}
    for label in RELATION_LABELS:
        tp = fp = fn = 0
        for candidate_id, gold_row in gold_by_id.items():
            pred_label = (
                pred_by_id[candidate_id].label
                if candidate_id in pred_by_id
                else "__missing__"
            )
            if gold_row.label == label and pred_label == label:
                tp += 1
            elif gold_row.label != label and pred_label == label:
                fp += 1
            elif gold_row.label == label and pred_label != label:
                fn += 1
        per_label[label] = _prf(tp, fp, fn)
    return {
        "macro_f1": round(
            sum(float(row["f1"]) for row in per_label.values()) / len(RELATION_LABELS),
            6,
        ),
        "per_label": per_label,
        "candidate_count": len(gold_by_id),
    }


def attribution_claim_metrics(
    gold: list[EvaluationClaim],
    prediction: list[EvaluationClaim],
    gold_spans: list[EvaluationEvidenceSpan],
    prediction_spans: list[EvaluationEvidenceSpan],
    *,
    rules: SemanticEquivalenceRules,
    span_threshold: float = 0.5,
) -> dict:
    matches = _match_claims(
        gold,
        prediction,
        gold_spans,
        prediction_spans,
        rules=rules,
        span_threshold=span_threshold,
        require_holder=True,
    )
    metrics = _prf(
        len(matches), len(prediction) - len(matches), len(gold) - len(matches)
    )
    return {**metrics, "matches": matches}


def _match_claims(
    gold: list[EvaluationClaim],
    prediction: list[EvaluationClaim],
    gold_spans: list[EvaluationEvidenceSpan],
    prediction_spans: list[EvaluationEvidenceSpan],
    *,
    rules: SemanticEquivalenceRules,
    span_threshold: float,
    require_holder: bool,
) -> list[dict]:
    graph = nx.Graph()
    pair_results: dict[tuple[int, int], dict] = {}
    for gold_index, gold_claim in enumerate(gold):
        graph.add_node(("gold", gold_index), bipartite=0)
        for pred_index, pred_claim in enumerate(prediction):
            graph.add_node(("pred", pred_index), bipartite=1)
            if not _claim_structure_matches(
                gold_claim, pred_claim, require_holder=require_holder
            ):
                continue
            explanation = match_explanation(
                gold_explanation=gold_claim.explanation,
                prediction_explanation=pred_claim.explanation,
                gold_links=_as_ea_links(gold_spans, gold_claim.claim_id),
                prediction_links=_as_ea_links(prediction_spans, pred_claim.claim_id),
                rules=rules,
                span_f1_threshold=span_threshold,
            )
            if not explanation.matched:
                continue
            pair_results[(gold_index, pred_index)] = {
                "gold_index": gold_index,
                "pred_index": pred_index,
                "gold_claim_id": gold_claim.claim_id,
                "pred_claim_id": pred_claim.claim_id,
                "explanation_match_method": explanation.method,
                "explanation_score": explanation.score,
                "rule_version": explanation.rule_version,
            }
            graph.add_edge(
                ("gold", gold_index),
                ("pred", pred_index),
                weight=2.0 if explanation.method == "span_overlap" else 1.0,
            )
    matching = nx.algorithms.matching.max_weight_matching(
        graph, maxcardinality=True, weight="weight"
    )
    matches = []
    for left, right in matching:
        gold_node, pred_node = (left, right) if left[0] == "gold" else (right, left)
        matches.append(pair_results[(gold_node[1], pred_node[1])])
    matches.sort(key=lambda row: (row["gold_index"], row["pred_index"]))
    return matches


def attribution_holder_accuracy(
    gold: list[EvaluationClaim], prediction: list[EvaluationClaim], matches: list[dict]
) -> dict[str, float | int]:
    correct = sum(
        gold[row["gold_index"]].attribution_holder_category
        == prediction[row["pred_index"]].attribution_holder_category
        for row in matches
    )
    return {
        "correct": correct,
        "matched_claims": len(matches),
        "accuracy": round(correct / len(matches), 6) if matches else 0.0,
    }


def holder_category_mismatch_rate(
    gold: list[EvaluationClaim], prediction: list[EvaluationClaim], matches: list[dict]
) -> dict[str, float | int]:
    mismatches = 0
    for row in matches:
        gold_claim = gold[row["gold_index"]]
        pred_claim = prediction[row["pred_index"]]
        gold_same = (
            gold_claim.stakeholder_category == gold_claim.attribution_holder_category
        )
        pred_same = (
            pred_claim.stakeholder_category == pred_claim.attribution_holder_category
        )
        mismatches += gold_same != pred_same
    return {
        "mismatches": mismatches,
        "matched_claims": len(matches),
        "rate": round(mismatches / len(matches), 6) if matches else 0.0,
    }


def evidence_span_character_f1(
    gold: list[EvaluationEvidenceSpan], prediction: list[EvaluationEvidenceSpan]
) -> dict[str, float | int]:
    gold_positions = _span_position_counter(gold)
    pred_positions = _span_position_counter(prediction)
    return _counter_prf(gold_positions, pred_positions)


def unsupported_claim_rate(
    claims: list[EvaluationClaim], spans: list[EvaluationEvidenceSpan]
) -> dict[str, float | int]:
    supported_ids = {
        row.target_id
        for row in spans
        if row.target_type == "claim" and row.support_label == "supports"
    }
    unsupported = sum(row.claim_id not in supported_ids for row in claims)
    return {
        "unsupported": unsupported,
        "claims": len(claims),
        "rate": round(unsupported / len(claims), 6) if claims else 0.0,
    }


def verification_error_rates(rows: list[VerificationDecisionItem]) -> dict:
    _unique_by_id(rows, "candidate_id", "verification decisions")
    accepted_gold = sum(row.gold_accept for row in rows)
    rejected_gold = len(rows) - accepted_gold
    false_acceptance = sum(
        not row.gold_accept and row.predicted_status == "verified" for row in rows
    )
    false_rejection = sum(
        row.gold_accept and row.predicted_status != "verified" for row in rows
    )
    return {
        "false_acceptance": false_acceptance,
        "false_acceptance_rate": round(false_acceptance / rejected_gold, 6)
        if rejected_gold
        else 0.0,
        "false_rejection": false_rejection,
        "false_rejection_rate": round(false_rejection / accepted_gold, 6)
        if accepted_gold
        else 0.0,
        "gold_accept": accepted_gold,
        "gold_reject": rejected_gold,
    }


def _claim_structure_matches(
    gold: EvaluationClaim,
    prediction: EvaluationClaim,
    *,
    require_holder: bool,
) -> bool:
    core_matches = (
        gold.document_id,
        gold.stakeholder_category,
        gold.effect_type,
        gold.effect_value,
        gold.relation_type,
    ) == (
        prediction.document_id,
        prediction.stakeholder_category,
        prediction.effect_type,
        prediction.effect_value,
        prediction.relation_type,
    )
    return core_matches and (
        not require_holder
        or gold.attribution_holder_category == prediction.attribution_holder_category
    )


def _as_ea_links(
    rows: list[EvaluationEvidenceSpan], target_id: str
) -> list[EAEvidenceLink]:
    output = []
    for index, row in enumerate(rows):
        if row.target_type != "claim" or row.target_id != target_id:
            continue
        output.append(
            EAEvidenceLink(
                evidence_link_id=f"eval-{target_id}-{index}",
                target_type="claim",
                target_id=target_id,
                document_id=row.document_id,
                evidence_id=f"eval-evidence-{index}",
                span_id=f"eval-span-{index}",
                char_start=row.char_start,
                char_end=row.char_end,
                span_text=row.span_text,
                support_field=row.support_field,
                support_label=row.support_label,
            )
        )
    return output


def _span_position_counter(
    rows: list[EvaluationEvidenceSpan],
) -> Counter[tuple[str, str, str, int]]:
    output: Counter[tuple[str, str, str, int]] = Counter()
    for row in rows:
        if row.support_label != "supports":
            continue
        for position in range(row.char_start, row.char_end):
            output[(row.document_id, row.target_type, row.support_field, position)] += 1
    return output


def _counter_prf(gold: Counter, prediction: Counter) -> dict[str, float | int]:
    tp = sum((gold & prediction).values())
    fp = sum(prediction.values()) - tp
    fn = sum(gold.values()) - tp
    return _prf(tp, fp, fn)


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _unique_by_id(rows, field: str, label: str):
    output = {}
    for row in rows:
        value = getattr(row, field)
        if value in output:
            raise ValueError(f"{label} contain duplicate {field}: {value}")
        output[value] = row
    return output


def _normalize_text(value: str) -> str:
    return "".join(str(value or "").lower().split())
