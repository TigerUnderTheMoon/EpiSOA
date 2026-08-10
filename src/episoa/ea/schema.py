"""Frozen EpiSOA-EA formal and process schemas."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StakeholderCategory = Literal[
    "government",
    "public_institution",
    "enterprise",
    "affected_public",
    "social_organization",
    "expert",
    "media",
    "general_public",
    "other_or_unknown",
]
EffectType = Literal["stance", "emotion", "action"]
StanceValue = Literal["support", "oppose", "question", "neutral", "uncertain"]
EmotionValue = Literal["positive", "negative", "neutral", "uncertain"]
EventStage = Literal[
    "trigger", "diffusion", "conflict", "response", "resolution", "follow_up", "unknown"
]
RelationType = Literal["stance_rationale", "emotion_trigger", "action_motivation"]
RelationDecision = Literal["supported", "no_relation"]
RelationEvaluationLabel = Literal[
    "stance_rationale", "emotion_trigger", "action_motivation", "no_relation"
]
VerificationStatus = Literal["verified", "insufficient", "rejected"]
EvidenceSupportLabel = Literal["supports", "contradicts", "insufficient"]
EvidenceTargetType = Literal["effect", "claim"]
DerivationType = Literal[
    "original",
    "independent_report",
    "official_republication",
    "syndicated_copy",
    "quoted_from_other_source",
    "synthesized_from_multiple_sources",
    "unknown",
]
SourceType = Literal[
    "news", "official", "public_interaction", "forum", "public_social", "public_web"
]
Explicitness = Literal["explicit", "implicit"]
Certainty = Literal["certain", "uncertain"]
Polarity = Literal["affirmed", "denied"]
ClaimPairRelation = Literal[
    "equivalent_explanation", "additional", "explicitly_contradicted", "unresolved"
]
ClaimGroupStatus = Literal[
    "corroborated", "complementary", "contested", "unresolved", "single_source"
]
CanonicalTargetType = Literal["effect", "claim"]
CanonicalResolutionStatus = Literal["needs_adjudication", "adjudicated"]
RawContentKind = Literal["full_text", "summary"]
EffectEvidenceField = Literal[
    "holder_surface",
    "stakeholder_category",
    "effect_type",
    "effect_value",
    "target",
    "effect_stage",
]
ClaimEvidenceField = Literal[
    "explanation_surface",
    "relation_type",
    "attribution_holder_surface",
    "attribution_holder_category",
    "explicitness",
    "certainty",
    "polarity",
]
M3Stage = Literal[
    "explanation", "relation", "effect_verification", "claim_verification"
]


RELATION_BY_EFFECT_TYPE: dict[str, str] = {
    "stance": "stance_rationale",
    "emotion": "emotion_trigger",
    "action": "action_motivation",
}
STANCE_VALUES = {"support", "oppose", "question", "neutral", "uncertain"}
EMOTION_VALUES = {"positive", "negative", "neutral", "uncertain"}
EFFECT_EVIDENCE_FIELDS = frozenset(
    {
        "holder_surface",
        "stakeholder_category",
        "effect_type",
        "effect_value",
        "target",
        "effect_stage",
    }
)
CLAIM_EVIDENCE_FIELDS = frozenset(
    {
        "explanation_surface",
        "relation_type",
        "attribution_holder_surface",
        "attribution_holder_category",
        "explicitness",
        "certainty",
        "polarity",
    }
)
CLAIM_REQUIRED_EVIDENCE_FIELDS = CLAIM_EVIDENCE_FIELDS - {
    "attribution_holder_surface"
}
CLAIM_VERIFICATION_FIELDS = frozenset(
    {
        "effect_grounded",
        "explanation_grounded",
        "relation_grounded",
        "direction_correct",
        "effect_holder_grounded",
        "attribution_holder_grounded",
        "certainty_correct",
        "polarity_correct",
    }
)


class EABaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRecord(EABaseModel):
    source_id: str = Field(..., min_length=1)
    source_name: str = Field(..., min_length=1)
    source_type: SourceType


class RawDocumentInput(EABaseModel):
    """M2 input row; source metadata are materialized into sources.jsonl."""

    document_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    reporting_source: SourceRecord
    primary_source: SourceRecord | None = None
    parent_document_id: str | None = None
    publication_time: str | None = None
    derivation_type: DerivationType
    title: str | None = None
    summary_text: str | None = None
    body_text: str
    content_kind: RawContentKind
    declared_content_hash: str | None = None
    url: str | None = None


class DocumentRecord(EABaseModel):
    document_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    reporting_source_id: str = Field(..., min_length=1)
    primary_source_id: str = Field(..., min_length=1)
    parent_document_id: str | None = None
    publication_time: str | None = None
    content_hash: str = Field(..., min_length=1)
    derivation_type: DerivationType
    normalized_text: str = Field(..., min_length=1)
    url: str | None = None

    @model_validator(mode="after")
    def validate_content_hash(self) -> DocumentRecord:
        expected = content_hash(self.normalized_text)
        if self.content_hash != expected:
            raise ValueError(f"content_hash must equal {expected}")
        return self


class EffectFields(EABaseModel):
    effect_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    reporting_source_id: str = Field(..., min_length=1)
    primary_source_id: str = Field(..., min_length=1)
    derivation_type: DerivationType
    stakeholder_category: StakeholderCategory
    holder_surface: str = Field(..., min_length=1)
    holder_role: str | None = None
    effect_type: EffectType
    effect_surface: str = Field(..., min_length=1)
    effect_value: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    effect_stage: EventStage

    @model_validator(mode="after")
    def validate_effect_value(self) -> EffectFields:
        if self.effect_type == "stance" and self.effect_value not in STANCE_VALUES:
            raise ValueError("stance effect_value must use the frozen stance labels")
        if self.effect_type == "emotion" and self.effect_value not in EMOTION_VALUES:
            raise ValueError("emotion effect_value must use the frozen emotion labels")
        return self


class EffectCandidateRecord(EffectFields):
    """Process record written before field-level verification."""


class EffectEvidenceSpan(EABaseModel):
    support_field: EffectEvidenceField
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., gt=0)
    span_text: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> EffectEvidenceSpan:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class ExtractedEffectPayload(EABaseModel):
    """LLM-facing M2 payload before IDs and document provenance are attached."""

    stakeholder_category: StakeholderCategory
    holder_surface: str = Field(..., min_length=1)
    holder_role: str | None = None
    effect_type: EffectType
    effect_surface: str = Field(..., min_length=1)
    effect_value: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    effect_stage: EventStage
    expression_present: Literal[True]
    emotion_state_present: Literal[True] | None = None
    evidence_spans: list[EffectEvidenceSpan] = Field(..., min_length=6)

    @model_validator(mode="after")
    def validate_extraction_contract(self) -> ExtractedEffectPayload:
        if self.effect_type == "stance" and self.effect_value not in STANCE_VALUES:
            raise ValueError("stance effect_value must use the frozen stance labels")
        if self.effect_type == "emotion":
            if self.effect_value not in EMOTION_VALUES:
                raise ValueError(
                    "emotion effect_value must use the frozen emotion labels"
                )
            if self.emotion_state_present is not True:
                raise ValueError("emotion effects require an expressed emotion state")
        elif self.emotion_state_present is not None:
            raise ValueError("emotion_state_present is only valid for emotion effects")
        fields = [span.support_field for span in self.evidence_spans]
        if len(fields) != len(set(fields)):
            raise ValueError("each Effect evidence field must occur exactly once")
        if set(fields) != EFFECT_EVIDENCE_FIELDS:
            missing = sorted(EFFECT_EVIDENCE_FIELDS - set(fields))
            extra = sorted(set(fields) - EFFECT_EVIDENCE_FIELDS)
            raise ValueError(
                f"invalid Effect evidence fields; missing={missing}, extra={extra}"
            )
        return self


class EffectExtractionResponse(EABaseModel):
    effects: list[ExtractedEffectPayload] = Field(default_factory=list)


class ExtractionAttemptRecord(EABaseModel):
    attempt_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    chunk_id: str = Field(..., min_length=1)
    chunk_start: int = Field(..., ge=0)
    chunk_end: int = Field(..., gt=0)
    attempt_number: int = Field(..., ge=1)
    response_id: str = ""
    raw_response: str
    valid: bool
    parse_error: str | None = None


class ViewpointEffect(EffectFields):
    """Formal verified Effect record."""

    canonical_effect_id: str | None = None


class ClaimEvidenceSpan(EABaseModel):
    support_field: ClaimEvidenceField
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., gt=0)
    span_text: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> ClaimEvidenceSpan:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class ExplanationCandidatePayload(EABaseModel):
    explanation_surface: str = Field(..., min_length=1)
    normalized_explanation: str = Field(..., min_length=1)
    candidate_source: Literal[
        "explicit_cue",
        "argument_structure",
        "cross_sentence",
        "temporal_compatible",
        "llm_proposed",
    ]
    evidence_spans: list[ClaimEvidenceSpan] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_explanation_evidence(self) -> ExplanationCandidatePayload:
        if {span.support_field for span in self.evidence_spans} != {
            "explanation_surface"
        }:
            raise ValueError(
                "Explanation Candidate evidence may only support explanation_surface"
            )
        return self


class ExplanationCandidateResponse(EABaseModel):
    candidates: list[ExplanationCandidatePayload] = Field(default_factory=list)


class ExplanationCandidateRecord(EABaseModel):
    explanation_candidate_id: str = Field(..., min_length=1)
    effect_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    explanation_surface: str = Field(..., min_length=1)
    normalized_explanation: str = Field(..., min_length=1)
    candidate_source: Literal[
        "explicit_cue",
        "argument_structure",
        "cross_sentence",
        "temporal_compatible",
        "llm_proposed",
    ]
    evidence_spans: list[ClaimEvidenceSpan] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_document_evidence(self) -> ExplanationCandidateRecord:
        if {span.support_field for span in self.evidence_spans} != {
            "explanation_surface"
        }:
            raise ValueError(
                "Explanation Candidate evidence may only support explanation_surface"
            )
        return self


class RelationJudgmentPayload(EABaseModel):
    relation_decision: RelationDecision
    relation_type: RelationType | None = None
    attribution_holder_category: StakeholderCategory
    attribution_holder_surface: str | None = None
    attribution_holder_role: str | None = None
    claim_stage: EventStage
    explicitness: Explicitness
    certainty: Certainty
    polarity: Polarity
    evidence_spans: list[ClaimEvidenceSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_relation_payload(self) -> RelationJudgmentPayload:
        if self.relation_decision == "no_relation":
            if self.relation_type is not None:
                raise ValueError("no_relation judgments must not carry relation_type")
            return self
        fields = [span.support_field for span in self.evidence_spans]
        expected = set(CLAIM_REQUIRED_EVIDENCE_FIELDS)
        if self.attribution_holder_surface is not None:
            expected.add("attribution_holder_surface")
        if len(fields) != len(set(fields)) or set(fields) != expected:
            raise ValueError(
                "supported judgments require exactly one span for every Claim field"
            )
        return self


class RelationJudgmentResponse(EABaseModel):
    judgment: RelationJudgmentPayload


class RelationJudgmentRecord(EABaseModel):
    relation_judgment_id: str = Field(..., min_length=1)
    explanation_candidate_id: str = Field(..., min_length=1)
    effect_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    effect_type: EffectType
    relation_decision: RelationDecision
    relation_type: RelationType | None = None
    attribution_holder_category: StakeholderCategory
    attribution_holder_surface: str | None = None
    attribution_holder_role: str | None = None
    claim_stage: EventStage
    explicitness: Explicitness
    certainty: Certainty
    polarity: Polarity
    evidence_spans: list[ClaimEvidenceSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_relation_contract(self) -> RelationJudgmentRecord:
        if self.relation_decision == "no_relation" and self.relation_type is not None:
            raise ValueError("no_relation judgments must not carry relation_type")
        expected = RELATION_BY_EFFECT_TYPE[self.effect_type]
        if self.relation_decision == "supported" and self.relation_type != expected:
            raise ValueError(
                f"supported {self.effect_type} judgment requires relation_type={expected}"
            )
        if self.relation_decision == "supported":
            fields = [span.support_field for span in self.evidence_spans]
            expected_fields = set(CLAIM_REQUIRED_EVIDENCE_FIELDS)
            if self.attribution_holder_surface is not None:
                expected_fields.add("attribution_holder_surface")
            if len(fields) != len(set(fields)) or set(fields) != expected_fields:
                raise ValueError(
                    "supported judgments require exactly one span for every Claim field"
                )
        return self


class EffectVerificationResponse(EABaseModel):
    holder_surface: VerificationStatus
    stakeholder_category: VerificationStatus
    effect_type: VerificationStatus
    effect_value: VerificationStatus
    target: VerificationStatus
    effect_stage: VerificationStatus
    rationale: str | None = None


class ClaimVerificationResponse(EABaseModel):
    effect_grounded: VerificationStatus
    explanation_grounded: VerificationStatus
    relation_grounded: VerificationStatus
    direction_correct: VerificationStatus
    effect_holder_grounded: VerificationStatus
    attribution_holder_grounded: VerificationStatus
    certainty_correct: VerificationStatus
    polarity_correct: VerificationStatus
    rationale: str | None = None


class M3AttemptRecord(EABaseModel):
    attempt_id: str = Field(..., min_length=1)
    stage: M3Stage
    document_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    attempt_number: int = Field(..., ge=1)
    response_id: str = ""
    raw_response: str
    valid: bool
    parse_error: str | None = None


class AttributionClaim(EABaseModel):
    claim_id: str = Field(..., min_length=1)
    effect_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    reporting_source_id: str = Field(..., min_length=1)
    primary_source_id: str = Field(..., min_length=1)
    derivation_type: DerivationType
    explanation_surface: str = Field(..., min_length=1)
    normalized_explanation: str = Field(..., min_length=1)
    relation_type: RelationType
    attribution_holder_category: StakeholderCategory
    attribution_holder_surface: str | None = None
    attribution_holder_role: str | None = None
    claim_stage: EventStage
    explicitness: Explicitness
    certainty: Certainty
    polarity: Polarity
    canonical_claim_group_id: str | None = None


class EvidenceLink(EABaseModel):
    evidence_link_id: str = Field(..., min_length=1)
    target_type: EvidenceTargetType
    target_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    evidence_id: str = Field(..., min_length=1)
    span_id: str = Field(..., min_length=1)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., gt=0)
    span_text: str = Field(..., min_length=1)
    support_field: str = Field(..., min_length=1)
    support_label: EvidenceSupportLabel

    @model_validator(mode="after")
    def validate_offsets(self) -> EvidenceLink:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class VerificationDiagnosticRecord(EABaseModel):
    verification_id: str = Field(..., min_length=1)
    target_type: EvidenceTargetType
    target_id: str = Field(..., min_length=1)
    status: VerificationStatus
    field_statuses: dict[str, VerificationStatus] = Field(default_factory=dict)
    issue_flags: list[str] = Field(default_factory=list)
    rationale: str | None = None


class CanonicalClaimGroup(EABaseModel):
    canonical_claim_group_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    canonical_effect_id: str = Field(..., min_length=1)
    relation_type: RelationType
    normalized_explanation: str = Field(..., min_length=1)
    attribution_holder_category: StakeholderCategory
    polarity: Polarity
    claim_ids: list[str] = Field(..., min_length=1)
    group_status: ClaimGroupStatus = "single_source"
    document_multiplicity: int = Field(default=0, ge=0)
    primary_source_multiplicity: int = Field(default=0, ge=0)
    dependent_reproduction_count: int = Field(default=0, ge=0)
    unknown_lineage_count: int = Field(default=0, ge=0)


class CanonicalEffect(EABaseModel):
    """Category-level viewpoint proposition; never an actor-coreference record."""

    canonical_effect_id: str = Field(..., pattern=r"^ce_[0-9a-f]{16}$")
    event_id: str = Field(..., min_length=1)
    stakeholder_category: StakeholderCategory
    effect_type: EffectType
    normalized_effect_value: str = Field(..., min_length=1)
    normalized_target: str = Field(..., min_length=1)
    member_effect_ids: list[str] = Field(..., min_length=1)
    observed_stages: list[EventStage] = Field(..., min_length=1)
    document_multiplicity: int = Field(default=0, ge=0)
    primary_source_multiplicity: int = Field(default=0, ge=0)
    dependent_reproduction_count: int = Field(default=0, ge=0)
    unknown_lineage_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_membership(self) -> CanonicalEffect:
        if self.member_effect_ids != sorted(set(self.member_effect_ids)):
            raise ValueError("member_effect_ids must be sorted and unique")
        if self.observed_stages != sorted(set(self.observed_stages)):
            raise ValueError("observed_stages must be sorted and unique")
        return self


FusionTargetType = Literal["effect", "claim"]
FusionSemanticLabel = Literal[
    "equivalent_effect",
    "distinct_effect",
    "equivalent_explanation",
    "additional",
    "explicitly_contradicted",
    "unresolved",
]
MergeDecision = Literal["must_link", "cannot_link", "needs_adjudication"]
TemporalCompatibility = Literal["compatible", "conflict", "uncertain"]


class SemanticPairJudgmentRecord(EABaseModel):
    pair_id: str = Field(..., min_length=1)
    target_type: FusionTargetType
    event_id: str = Field(..., min_length=1)
    left_id: str = Field(..., min_length=1)
    right_id: str = Field(..., min_length=1)
    semantic_label: FusionSemanticLabel
    semantic_score: float | None = Field(default=None, ge=0.0, le=1.0)
    temporal_compatibility: TemporalCompatibility = "compatible"
    judgment_resource_id: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    prompt_version: str = Field(..., min_length=1)
    decoding_version: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_pair(self) -> SemanticPairJudgmentRecord:
        if self.left_id >= self.right_id:
            raise ValueError("pair member IDs must be sorted")
        return self


class FusionPairJudgmentRecord(SemanticPairJudgmentRecord):
    merge_decision: MergeDecision
    constraint_results: dict[str, bool] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    rule_version: str = Field(..., min_length=1)


class FusionClusterDiagnosticRecord(EABaseModel):
    diagnostic_id: str = Field(..., min_length=1)
    target_type: FusionTargetType
    event_id: str = Field(..., min_length=1)
    left_cluster_ids: list[str] = Field(..., min_length=1)
    right_cluster_ids: list[str] = Field(..., min_length=1)
    decision: MergeDecision
    blocking_pair_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class DossierProvenanceRecord(EABaseModel):
    canonical_claim_group_id: str = Field(..., min_length=1)
    claim_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    reporting_source_id: str = Field(..., min_length=1)
    primary_source_id: str = Field(..., min_length=1)
    evidence_link_ids: list[str] = Field(..., min_length=1)


class DossierEdge(EABaseModel):
    edge_type: Literal[
        "contains",
        "canonicalized_as",
        "belongs_to",
        "supported_by",
        "reported_in",
        "reported_by",
        "derived_from",
        "claim_about_effect",
        "claim_pair_relation",
    ]
    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)


class EventDossierRecord(EABaseModel):
    event_id: str = Field(..., min_length=1)
    canonical_effect_ids: list[str] = Field(default_factory=list)
    canonical_claim_group_ids: list[str] = Field(default_factory=list)
    claim_pair_relation_ids: list[str] = Field(default_factory=list)
    provenance: list[DossierProvenanceRecord] = Field(default_factory=list)
    edges: list[DossierEdge] = Field(default_factory=list)
    dossier_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")


class ClaimPairRelationRecord(EABaseModel):
    claim_pair_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    left_claim_id: str = Field(..., min_length=1)
    right_claim_id: str = Field(..., min_length=1)
    left_primary_source_id: str = Field(..., min_length=1)
    right_primary_source_id: str = Field(..., min_length=1)
    relation: ClaimPairRelation

    @model_validator(mode="after")
    def validate_independent_sources(self) -> ClaimPairRelationRecord:
        if self.left_claim_id == self.right_claim_id:
            raise ValueError("claim pair must contain two different claims")
        if self.left_primary_source_id == self.right_primary_source_id:
            raise ValueError("claim pair requires different primary_source_id values")
        return self


class CanonicalAdjudicationRecord(EABaseModel):
    adjudication_id: str = Field(..., min_length=1)
    target_type: CanonicalTargetType
    event_id: str = Field(..., min_length=1)
    record_ids: list[str] = Field(..., min_length=2)
    reason: str = Field(..., min_length=1)
    status: CanonicalResolutionStatus = "needs_adjudication"
    adjudicated_canonical_id: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> CanonicalAdjudicationRecord:
        if self.status == "adjudicated" and not self.adjudicated_canonical_id:
            raise ValueError("adjudicated rows require adjudicated_canonical_id")
        if (
            self.status == "needs_adjudication"
            and self.adjudicated_canonical_id is not None
        ):
            raise ValueError("unresolved rows must not carry adjudicated_canonical_id")
        return self


def content_hash(normalized_text: str) -> str:
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
