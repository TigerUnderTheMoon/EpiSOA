"""Synthetic-ready M3 explanation, attribution, verification, and promotion chain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from episoa.ea.promotion import EffectPromotionResult, promote_effect_candidates
from episoa.ea.schema import (
    CLAIM_REQUIRED_EVIDENCE_FIELDS,
    CLAIM_VERIFICATION_FIELDS,
    RELATION_BY_EFFECT_TYPE,
    AttributionClaim,
    ClaimVerificationResponse,
    DocumentRecord,
    EffectCandidateRecord,
    EffectVerificationResponse,
    EvidenceLink,
    ExplanationCandidateRecord,
    ExplanationCandidateResponse,
    M3AttemptRecord,
    RelationJudgmentRecord,
    RelationJudgmentResponse,
    VerificationDiagnosticRecord,
)
from episoa.llm.client import json_schema_response_format

EXPLANATION_SYSTEM_PROMPT = """你是EpiSOA-EA的Explanation Candidate构造器。
输入只包含一个document_id、一条不可改写的Effect和该文档正文。只能从当前文档构造解释候选，禁止使用其他文档信息。
候选来源只允许explicit_cue、argument_structure、cross_sentence、temporal_compatible、llm_proposed。
候选只表示文档内可能解释该Effect的命题，不等于关系已成立，也不等于现实世界真实原因。
每个候选必须提供当前document normalized_text中的explanation_surface精确Evidence Span。不要输出Relation、AttributionHolder、Claim或Canonical字段。"""

RELATION_SYSTEM_PROMPT = """你是EpiSOA-EA的双主体关系判断器。
输入只包含同一document_id中的不可改写Effect、Explanation Candidate和正文。EffectHolder由Effect固定，禁止重新分类或改写。
relation_decision只能为supported或no_relation。supported时，stance唯一映射stance_rationale，emotion唯一映射emotion_trigger，action唯一映射action_motivation；no_relation不得带relation_type。
独立判断AttributionHolder Category、可为空的attribution_holder_surface、claim_stage、explicitness、certainty、polarity。ReportingSource只是发布渠道，不能自动视为AttributionHolder。只有原文明确出现AttributionHolder称谓时才填写surface；隐式归因或无明确称谓时必须为null，不得编造。
supported必须为explanation_surface、relation_type、attribution_holder_category、explicitness、certainty、polarity各提供一个当前文档中的精确Evidence Span；attribution_holder_surface非null时还必须提供对应Span。不要输出Canonical或Claim Pair。"""

EFFECT_VERIFIER_SYSTEM_PROMPT = """你是与生成步骤分离的EpiSOA-EA Effect字段证据验证器。
只依据当前document_id正文、Effect字段和给定Evidence Span验证holder_surface、stakeholder_category、effect_type、effect_value、target、effect_stage。
每个字段只能输出verified、insufficient或rejected。verified表示文档证据支持该字段；insufficient表示证据不足；rejected表示与正文冲突或明显错误。不要推断文档外事实。"""

CLAIM_VERIFIER_SYSTEM_PROMPT = """你是与生成步骤分离的EpiSOA-EA Claim字段证据验证器。
只依据当前document_id正文、不可改写Effect、Explanation Candidate、Relation Judgment和Evidence Span进行判断，不接收也不得推测生成器推理过程。
验证effect_grounded、explanation_grounded、relation_grounded、direction_correct、effect_holder_grounded、attribution_holder_grounded、certainty_correct、polarity_correct。
每个字段只能输出verified、insufficient或rejected。verified仅表示文本支持“该AttributionHolder提出了该解释及其与Effect的关系”，不表示解释是现实世界真实原因。"""


class M3Client(Protocol):
    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict | None = None,
    ): ...


@dataclass(frozen=True)
class M3Clients:
    explanation: M3Client
    relation: M3Client
    verifier: M3Client


@dataclass(frozen=True)
class ClaimPromotionFailure:
    relation_judgment_id: str
    claim_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class M3PipelineResult:
    explanation_candidates: tuple[ExplanationCandidateRecord, ...]
    relation_judgments: tuple[RelationJudgmentRecord, ...]
    verification_diagnostics: tuple[VerificationDiagnosticRecord, ...]
    effect_promotion: EffectPromotionResult
    claims: tuple[AttributionClaim, ...]
    evidence_links: tuple[EvidenceLink, ...]
    claim_failures: tuple[ClaimPromotionFailure, ...]
    attempts: tuple[M3AttemptRecord, ...]


T = TypeVar("T", bound=BaseModel)


def run_m3_core(
    *,
    documents: list[DocumentRecord],
    effect_candidates: list[EffectCandidateRecord],
    effect_evidence_links: list[EvidenceLink],
    clients: M3Clients,
    schema_retries: int = 1,
) -> M3PipelineResult:
    """Run M3 without requiring real pilot data or mutating M2 candidates."""
    if schema_retries < 0:
        raise ValueError("schema_retries must be non-negative")
    document_by_id = {row.document_id: row for row in documents}
    if len(document_by_id) != len(documents):
        raise ValueError("duplicate document_id in M3 input")
    _validate_effect_inputs(
        effect_candidates, effect_evidence_links, document_by_id=document_by_id
    )

    attempts: list[M3AttemptRecord] = []
    explanations = _build_explanations(
        effect_candidates,
        effect_evidence_links,
        document_by_id,
        clients.explanation,
        attempts,
        schema_retries,
    )
    judgments = _judge_relations(
        effect_candidates,
        explanations,
        document_by_id,
        clients.relation,
        attempts,
        schema_retries,
    )
    effect_diagnostics = _verify_effects(
        effect_candidates,
        effect_evidence_links,
        document_by_id,
        clients.verifier,
        attempts,
        schema_retries,
    )
    effect_promotion = promote_effect_candidates(
        effect_candidates, effect_evidence_links, effect_diagnostics
    )
    claim_diagnostics = _verify_claim_candidates(
        effect_candidates,
        explanations,
        judgments,
        document_by_id,
        clients.verifier,
        attempts,
        schema_retries,
    )
    claims, claim_links, failures = _promote_claims(
        explanations,
        judgments,
        claim_diagnostics,
        list(effect_promotion.formal_effects),
        document_by_id,
    )
    all_links = (*effect_evidence_links, *claim_links)
    return M3PipelineResult(
        tuple(explanations),
        tuple(judgments),
        (*effect_promotion.diagnostics, *claim_diagnostics),
        effect_promotion,
        tuple(claims),
        all_links,
        tuple(failures),
        tuple(attempts),
    )


def _build_explanations(
    effects: list[EffectCandidateRecord],
    links: list[EvidenceLink],
    document_by_id: dict[str, DocumentRecord],
    client: M3Client,
    attempts: list[M3AttemptRecord],
    schema_retries: int,
) -> list[ExplanationCandidateRecord]:
    output: dict[str, ExplanationCandidateRecord] = {}
    links_by_effect = _links_by_target(links, "effect")
    for effect in effects:
        document = document_by_id[effect.document_id]
        payload = {
            "document_id": document.document_id,
            "normalized_text": document.normalized_text,
            "effect": effect.model_dump(),
            "effect_evidence": [
                row.model_dump() for row in links_by_effect.get(effect.effect_id, [])
            ],
        }
        response = _call_schema(
            client=client,
            stage="explanation",
            document=document,
            target_id=effect.effect_id,
            response_model=ExplanationCandidateResponse,
            system_prompt=EXPLANATION_SYSTEM_PROMPT,
            payload=payload,
            attempts=attempts,
            schema_retries=schema_retries,
            validator=lambda row, text=document.normalized_text: _validate_spans(
                row.candidates, text
            ),
        )
        for candidate in response.candidates:
            candidate_id = _stable_id(
                "EX",
                (
                    effect.effect_id,
                    candidate.normalized_explanation,
                    candidate.explanation_surface,
                    [span.model_dump() for span in candidate.evidence_spans],
                ),
            )
            output[candidate_id] = ExplanationCandidateRecord(
                explanation_candidate_id=candidate_id,
                effect_id=effect.effect_id,
                event_id=effect.event_id,
                document_id=effect.document_id,
                explanation_surface=candidate.explanation_surface,
                normalized_explanation=candidate.normalized_explanation,
                candidate_source=candidate.candidate_source,
                evidence_spans=candidate.evidence_spans,
            )
    return list(output.values())


def _judge_relations(
    effects: list[EffectCandidateRecord],
    explanations: list[ExplanationCandidateRecord],
    document_by_id: dict[str, DocumentRecord],
    client: M3Client,
    attempts: list[M3AttemptRecord],
    schema_retries: int,
) -> list[RelationJudgmentRecord]:
    effect_by_id = {row.effect_id: row for row in effects}
    output: list[RelationJudgmentRecord] = []
    for explanation in explanations:
        effect = effect_by_id[explanation.effect_id]
        if effect.document_id != explanation.document_id:
            raise ValueError("Explanation Candidate crosses document boundary")
        document = document_by_id[effect.document_id]
        judgment_id = _stable_id("RJ", explanation.explanation_candidate_id)
        payload = {
            "document_id": document.document_id,
            "normalized_text": document.normalized_text,
            "immutable_effect": effect.model_dump(),
            "explanation_candidate": explanation.model_dump(),
        }
        response = _call_schema(
            client=client,
            stage="relation",
            document=document,
            target_id=explanation.explanation_candidate_id,
            response_model=RelationJudgmentResponse,
            system_prompt=RELATION_SYSTEM_PROMPT,
            payload=payload,
            attempts=attempts,
            schema_retries=schema_retries,
            validator=lambda row, current_effect=effect, text=document.normalized_text: (
                _validate_relation_response(row, current_effect, text)
            ),
        )
        judgment = response.judgment
        output.append(
            RelationJudgmentRecord(
                relation_judgment_id=judgment_id,
                explanation_candidate_id=explanation.explanation_candidate_id,
                effect_id=effect.effect_id,
                event_id=effect.event_id,
                document_id=effect.document_id,
                effect_type=effect.effect_type,
                relation_decision=judgment.relation_decision,
                relation_type=judgment.relation_type,
                attribution_holder_category=judgment.attribution_holder_category,
                attribution_holder_surface=judgment.attribution_holder_surface,
                attribution_holder_role=judgment.attribution_holder_role,
                claim_stage=judgment.claim_stage,
                explicitness=judgment.explicitness,
                certainty=judgment.certainty,
                polarity=judgment.polarity,
                evidence_spans=judgment.evidence_spans,
            )
        )
    return output


def _verify_effects(
    effects: list[EffectCandidateRecord],
    links: list[EvidenceLink],
    document_by_id: dict[str, DocumentRecord],
    client: M3Client,
    attempts: list[M3AttemptRecord],
    schema_retries: int,
) -> list[VerificationDiagnosticRecord]:
    links_by_effect = _links_by_target(links, "effect")
    output: list[VerificationDiagnosticRecord] = []
    for effect in effects:
        document = document_by_id[effect.document_id]
        payload = {
            "document_id": document.document_id,
            "normalized_text": document.normalized_text,
            "effect": effect.model_dump(),
            "effect_evidence": [
                row.model_dump() for row in links_by_effect.get(effect.effect_id, [])
            ],
        }
        response = _call_schema(
            client=client,
            stage="effect_verification",
            document=document,
            target_id=effect.effect_id,
            response_model=EffectVerificationResponse,
            system_prompt=EFFECT_VERIFIER_SYSTEM_PROMPT,
            payload=payload,
            attempts=attempts,
            schema_retries=schema_retries,
        )
        statuses = response.model_dump(exclude={"rationale"})
        output.append(
            VerificationDiagnosticRecord(
                verification_id=_stable_id("VER-EF", effect.effect_id),
                target_type="effect",
                target_id=effect.effect_id,
                status=_overall_status(statuses),
                field_statuses=statuses,
                rationale=response.rationale,
            )
        )
    return output


def _verify_claim_candidates(
    effects: list[EffectCandidateRecord],
    explanations: list[ExplanationCandidateRecord],
    judgments: list[RelationJudgmentRecord],
    document_by_id: dict[str, DocumentRecord],
    client: M3Client,
    attempts: list[M3AttemptRecord],
    schema_retries: int,
) -> list[VerificationDiagnosticRecord]:
    effect_by_id = {row.effect_id: row for row in effects}
    explanation_by_id = {row.explanation_candidate_id: row for row in explanations}
    output: list[VerificationDiagnosticRecord] = []
    for judgment in judgments:
        effect = effect_by_id[judgment.effect_id]
        explanation = explanation_by_id[judgment.explanation_candidate_id]
        document = document_by_id[judgment.document_id]
        claim_id = _claim_id(judgment)
        payload = {
            "document_id": document.document_id,
            "normalized_text": document.normalized_text,
            "immutable_effect": effect.model_dump(),
            "explanation_candidate": explanation.model_dump(),
            "relation_judgment": judgment.model_dump(),
        }
        response = _call_schema(
            client=client,
            stage="claim_verification",
            document=document,
            target_id=claim_id,
            response_model=ClaimVerificationResponse,
            system_prompt=CLAIM_VERIFIER_SYSTEM_PROMPT,
            payload=payload,
            attempts=attempts,
            schema_retries=schema_retries,
        )
        statuses = response.model_dump(exclude={"rationale"})
        if set(statuses) != CLAIM_VERIFICATION_FIELDS:
            raise ValueError("Claim verifier returned an incomplete field set")
        output.append(
            VerificationDiagnosticRecord(
                verification_id=_stable_id("VER-CL", claim_id),
                target_type="claim",
                target_id=claim_id,
                status=_overall_status(statuses),
                field_statuses=statuses,
                rationale=response.rationale,
            )
        )
    return output


def _promote_claims(
    explanations: list[ExplanationCandidateRecord],
    judgments: list[RelationJudgmentRecord],
    diagnostics: list[VerificationDiagnosticRecord],
    formal_effects,
    document_by_id: dict[str, DocumentRecord],
) -> tuple[list[AttributionClaim], list[EvidenceLink], list[ClaimPromotionFailure]]:
    explanation_by_id = {row.explanation_candidate_id: row for row in explanations}
    diagnostic_by_claim = {row.target_id: row for row in diagnostics}
    formal_effect_ids = {row.effect_id for row in formal_effects}
    claims: list[AttributionClaim] = []
    links: list[EvidenceLink] = []
    failures: list[ClaimPromotionFailure] = []
    for judgment in judgments:
        claim_id = _claim_id(judgment)
        diagnostic = diagnostic_by_claim[claim_id]
        reasons: list[str] = []
        if judgment.relation_decision != "supported":
            reasons.append("relation_decision:no_relation")
        if diagnostic.status != "verified":
            reasons.append(f"verification_status:{diagnostic.status}")
        if judgment.effect_id not in formal_effect_ids:
            reasons.append("effect_not_formal")
        evidence_fields = {span.support_field for span in judgment.evidence_spans}
        expected_evidence_fields = set(CLAIM_REQUIRED_EVIDENCE_FIELDS)
        if judgment.attribution_holder_surface is not None:
            expected_evidence_fields.add("attribution_holder_surface")
        if (
            judgment.relation_decision == "supported"
            and evidence_fields != expected_evidence_fields
        ):
            reasons.append("missing_claim_field_evidence")
        if reasons:
            failures.append(
                ClaimPromotionFailure(
                    judgment.relation_judgment_id, claim_id, tuple(reasons)
                )
            )
            continue

        explanation = explanation_by_id[judgment.explanation_candidate_id]
        document = document_by_id[judgment.document_id]
        claim = AttributionClaim(
            claim_id=claim_id,
            effect_id=judgment.effect_id,
            event_id=judgment.event_id,
            document_id=judgment.document_id,
            reporting_source_id=document.reporting_source_id,
            primary_source_id=document.primary_source_id,
            derivation_type=document.derivation_type,
            explanation_surface=explanation.explanation_surface,
            normalized_explanation=explanation.normalized_explanation,
            relation_type=judgment.relation_type,
            attribution_holder_category=judgment.attribution_holder_category,
            attribution_holder_surface=judgment.attribution_holder_surface,
            attribution_holder_role=judgment.attribution_holder_role,
            claim_stage=judgment.claim_stage,
            explicitness=judgment.explicitness,
            certainty=judgment.certainty,
            polarity=judgment.polarity,
        )
        claims.append(claim)
        for span in judgment.evidence_spans:
            span_id = _stable_id(
                "SP",
                (
                    document.document_id,
                    span.char_start,
                    span.char_end,
                    span.span_text,
                ),
            )
            links.append(
                EvidenceLink(
                    evidence_link_id=_stable_id(
                        "EL", (claim_id, span.support_field, span_id)
                    ),
                    target_type="claim",
                    target_id=claim_id,
                    document_id=document.document_id,
                    evidence_id=_stable_id(
                        "EV", (document.document_id, span.char_start, span.char_end)
                    ),
                    span_id=span_id,
                    char_start=span.char_start,
                    char_end=span.char_end,
                    span_text=span.span_text,
                    support_field=span.support_field,
                    support_label="supports",
                )
            )
    return claims, links, failures


def _call_schema(
    *,
    client: M3Client,
    stage: str,
    document: DocumentRecord,
    target_id: str,
    response_model: type[T],
    system_prompt: str,
    payload: dict,
    attempts: list[M3AttemptRecord],
    schema_retries: int,
    validator=None,
) -> T:
    last_error = ""
    for attempt_number in range(1, schema_retries + 2):
        request = dict(payload)
        if last_error:
            request["previous_validation_error"] = last_error
            request["instruction"] = "仅修正Schema或Evidence Span错误。"
        response = client.chat(
            system_prompt=system_prompt,
            user_prompt=json.dumps(request, ensure_ascii=False, sort_keys=True),
            response_format=json_schema_response_format(
                f"ea_m3_{stage}", response_model.model_json_schema()
            ),
        )
        raw = str(getattr(response, "content", "") or "")
        response_id = str(getattr(response, "response_id", "") or "")
        try:
            parsed = response_model.model_validate(json.loads(raw))
            if validator is not None:
                validator(parsed)
            attempts.append(
                _attempt(
                    stage,
                    document.document_id,
                    target_id,
                    attempt_number,
                    response_id,
                    raw,
                    valid=True,
                )
            )
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = " ".join(str(exc).split())[:1000]
            attempts.append(
                _attempt(
                    stage,
                    document.document_id,
                    target_id,
                    attempt_number,
                    response_id,
                    raw,
                    valid=False,
                    parse_error=last_error,
                )
            )
    raise ValueError(
        f"{stage}/{document.document_id}/{target_id}: invalid response after "
        f"{schema_retries + 1} attempts: {last_error}"
    )


def _validate_effect_inputs(
    effects: list[EffectCandidateRecord],
    links: list[EvidenceLink],
    *,
    document_by_id: dict[str, DocumentRecord],
) -> None:
    effect_ids: set[str] = set()
    effect_by_id: dict[str, EffectCandidateRecord] = {}
    for effect in effects:
        if effect.effect_id in effect_ids:
            raise ValueError(f"duplicate effect_id: {effect.effect_id}")
        effect_ids.add(effect.effect_id)
        effect_by_id[effect.effect_id] = effect
        document = document_by_id.get(effect.document_id)
        if document is None:
            raise ValueError(f"{effect.effect_id}: missing document")
        if (
            effect.event_id,
            effect.reporting_source_id,
            effect.primary_source_id,
            effect.derivation_type,
        ) != (
            document.event_id,
            document.reporting_source_id,
            document.primary_source_id,
            document.derivation_type,
        ):
            raise ValueError(f"{effect.effect_id}: document provenance mismatch")
    for link in links:
        if link.target_type != "effect" or link.target_id not in effect_ids:
            raise ValueError("M3 Effect evidence contains an unknown target")
        if link.document_id != effect_by_id[link.target_id].document_id:
            raise ValueError(
                f"{link.evidence_link_id}: Effect evidence crosses document boundary"
            )
        document = document_by_id.get(link.document_id)
        if document is None:
            raise ValueError(f"{link.evidence_link_id}: missing document")
        if document.normalized_text[link.char_start : link.char_end] != link.span_text:
            raise ValueError(f"{link.evidence_link_id}: Evidence Span mismatch")


def _validate_relation_response(
    response: RelationJudgmentResponse,
    effect: EffectCandidateRecord,
    text: str,
) -> None:
    judgment = response.judgment
    if judgment.relation_decision == "supported":
        expected = RELATION_BY_EFFECT_TYPE[effect.effect_type]
        if judgment.relation_type != expected:
            raise ValueError(
                f"supported {effect.effect_type} requires relation_type={expected}"
            )
    _validate_spans([judgment], text)


def _validate_spans(rows, text: str) -> None:
    for row in rows:
        if hasattr(row, "explanation_surface") and row.explanation_surface not in text:
            raise ValueError("explanation_surface is not present in current document")
        for span in row.evidence_spans:
            if span.char_end > len(text):
                raise ValueError("Evidence Span exceeds current document")
            if text[span.char_start : span.char_end] != span.span_text:
                raise ValueError(f"Evidence Span mismatch for {span.support_field}")


def _overall_status(statuses: dict[str, str]) -> str:
    values = set(statuses.values())
    if "rejected" in values:
        return "rejected"
    if values == {"verified"}:
        return "verified"
    return "insufficient"


def _links_by_target(
    links: list[EvidenceLink], target_type: str
) -> dict[str, list[EvidenceLink]]:
    output: dict[str, list[EvidenceLink]] = {}
    for link in links:
        if link.target_type == target_type:
            output.setdefault(link.target_id, []).append(link)
    return output


def _claim_id(judgment: RelationJudgmentRecord) -> str:
    return _stable_id("CL", judgment.relation_judgment_id)


def _attempt(
    stage: str,
    document_id: str,
    target_id: str,
    attempt_number: int,
    response_id: str,
    raw_response: str,
    *,
    valid: bool,
    parse_error: str | None = None,
) -> M3AttemptRecord:
    return M3AttemptRecord(
        attempt_id=_stable_id(
            "ATT-M3", (stage, document_id, target_id, attempt_number)
        ),
        stage=stage,
        document_id=document_id,
        target_id=target_id,
        attempt_number=attempt_number,
        response_id=response_id,
        raw_response=raw_response,
        valid=valid,
        parse_error=parse_error,
    )


def _stable_id(prefix: str, value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
