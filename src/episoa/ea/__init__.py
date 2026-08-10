"""Parallel EpiSOA-EA target-method implementation.

The legacy ``soe_v3`` pipeline remains under :mod:`episoa.pipeline`.  Modules in
this package use the frozen contracts from ``docs/method_framework.md`` and do
not read or write legacy paper artifacts.
"""

from episoa.ea.schema import (
    AttributionClaim,
    CanonicalAdjudicationRecord,
    CanonicalClaimGroup,
    CanonicalEffect,
    ClaimPairRelationRecord,
    ClaimVerificationResponse,
    DocumentRecord,
    EffectCandidateRecord,
    EffectExtractionResponse,
    EffectVerificationResponse,
    EventDossierRecord,
    EvidenceLink,
    ExplanationCandidateRecord,
    ExplanationCandidateResponse,
    ExtractedEffectPayload,
    ExtractionAttemptRecord,
    FusionClusterDiagnosticRecord,
    FusionPairJudgmentRecord,
    RawDocumentInput,
    RelationJudgmentRecord,
    RelationJudgmentResponse,
    SemanticPairJudgmentRecord,
    SourceRecord,
    VerificationDiagnosticRecord,
    ViewpointEffect,
)

__all__ = [
    "AttributionClaim",
    "CanonicalAdjudicationRecord",
    "CanonicalClaimGroup",
    "CanonicalEffect",
    "ClaimPairRelationRecord",
    "ClaimVerificationResponse",
    "DocumentRecord",
    "EffectCandidateRecord",
    "EffectExtractionResponse",
    "EffectVerificationResponse",
    "EventDossierRecord",
    "EvidenceLink",
    "ExplanationCandidateRecord",
    "ExplanationCandidateResponse",
    "ExtractedEffectPayload",
    "ExtractionAttemptRecord",
    "FusionClusterDiagnosticRecord",
    "FusionPairJudgmentRecord",
    "RawDocumentInput",
    "RelationJudgmentRecord",
    "RelationJudgmentResponse",
    "SemanticPairJudgmentRecord",
    "SourceRecord",
    "VerificationDiagnosticRecord",
    "ViewpointEffect",
]
