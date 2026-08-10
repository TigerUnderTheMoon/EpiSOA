"""Field-evidence gate from Effect candidates to formal Effects."""

from __future__ import annotations

from dataclasses import dataclass

from episoa.ea.schema import (
    EFFECT_EVIDENCE_FIELDS,
    EffectCandidateRecord,
    EvidenceLink,
    VerificationDiagnosticRecord,
    ViewpointEffect,
)

REQUIRED_EFFECT_SUPPORT_FIELDS = EFFECT_EVIDENCE_FIELDS


@dataclass(frozen=True)
class EffectPromotionFailure:
    effect_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EffectPromotionResult:
    formal_effects: tuple[ViewpointEffect, ...]
    failures: tuple[EffectPromotionFailure, ...]
    diagnostics: tuple[VerificationDiagnosticRecord, ...]


def promote_effect_candidates(
    candidates: list[EffectCandidateRecord],
    evidence_links: list[EvidenceLink],
    diagnostics: list[VerificationDiagnosticRecord],
) -> EffectPromotionResult:
    """Promote only candidates whose required fields are verified and supported."""
    diagnostics_by_target = {
        row.target_id: row for row in diagnostics if row.target_type == "effect"
    }
    support_fields_by_target: dict[str, set[str]] = {}
    for link in evidence_links:
        if link.target_type == "effect" and link.support_label == "supports":
            support_fields_by_target.setdefault(link.target_id, set()).add(
                link.support_field
            )

    formal: list[ViewpointEffect] = []
    failures: list[EffectPromotionFailure] = []
    effective_diagnostics: list[VerificationDiagnosticRecord] = []

    for candidate in candidates:
        diagnostic = diagnostics_by_target.get(candidate.effect_id)
        reasons: list[str] = []
        if diagnostic is None:
            reasons.append("missing_verification_diagnostic")
            diagnostic = _generated_diagnostic(candidate.effect_id, reasons)
        else:
            if diagnostic.status != "verified":
                reasons.append(f"verification_status:{diagnostic.status}")
            failed_fields = sorted(
                field
                for field in REQUIRED_EFFECT_SUPPORT_FIELDS
                if diagnostic.field_statuses.get(field) != "verified"
            )
            if failed_fields:
                reasons.append("unverified_fields:" + ",".join(failed_fields))

        missing_links = sorted(
            REQUIRED_EFFECT_SUPPORT_FIELDS
            - support_fields_by_target.get(candidate.effect_id, set())
        )
        if missing_links:
            reasons.append("missing_support_links:" + ",".join(missing_links))

        if reasons:
            if diagnostic.status == "verified":
                diagnostic = diagnostic.model_copy(
                    update={
                        "status": "insufficient",
                        "issue_flags": [*diagnostic.issue_flags, *reasons],
                    }
                )
            failures.append(EffectPromotionFailure(candidate.effect_id, tuple(reasons)))
        else:
            formal.append(ViewpointEffect(**candidate.model_dump()))
        effective_diagnostics.append(diagnostic)

    return EffectPromotionResult(
        tuple(formal), tuple(failures), tuple(effective_diagnostics)
    )


def _generated_diagnostic(
    effect_id: str, reasons: list[str]
) -> VerificationDiagnosticRecord:
    return VerificationDiagnosticRecord(
        verification_id=f"generated-{effect_id}",
        target_type="effect",
        target_id=effect_id,
        status="insufficient",
        field_statuses={},
        issue_flags=list(reasons),
        rationale="Effect did not satisfy the formal promotion gate.",
    )
