"""Cross-file referential and evidence-span validation for EpiSOA-EA."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from episoa.ea.schema import (
    CLAIM_REQUIRED_EVIDENCE_FIELDS,
    EFFECT_EVIDENCE_FIELDS,
    RELATION_BY_EFFECT_TYPE,
    AttributionClaim,
    CanonicalClaimGroup,
    ClaimPairRelationRecord,
    DocumentRecord,
    EvidenceLink,
    SourceRecord,
    ViewpointEffect,
)


class EAValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    record_id: str
    message: str


def validate_cross_file_references(
    *,
    sources: list[SourceRecord],
    documents: list[DocumentRecord],
    effects: list[ViewpointEffect],
    claims: list[AttributionClaim],
    evidence_links: list[EvidenceLink],
    claim_groups: list[CanonicalClaimGroup] | None = None,
    claim_pairs: list[ClaimPairRelationRecord] | None = None,
) -> list[EAValidationIssue]:
    issues: list[EAValidationIssue] = []
    source_by_id = _unique_index(sources, "source_id", issues)
    document_by_id = _unique_index(documents, "document_id", issues)
    effect_by_id = _unique_index(effects, "effect_id", issues)
    claim_by_id = _unique_index(claims, "claim_id", issues)
    group_by_id = _unique_index(claim_groups or [], "canonical_claim_group_id", issues)

    for document in documents:
        if document.reporting_source_id not in source_by_id:
            issues.append(
                _issue(
                    "missing_reporting_source",
                    document.document_id,
                    document.reporting_source_id,
                )
            )
        if document.primary_source_id not in source_by_id:
            issues.append(
                _issue(
                    "missing_primary_source",
                    document.document_id,
                    document.primary_source_id,
                )
            )
        if (
            document.parent_document_id
            and document.parent_document_id not in document_by_id
        ):
            issues.append(
                _issue(
                    "missing_parent_document",
                    document.document_id,
                    document.parent_document_id,
                )
            )

    support_fields: dict[tuple[str, str], set[str]] = {}
    for link in evidence_links:
        document = document_by_id.get(link.document_id)
        if document is None:
            issues.append(
                _issue("missing_link_document", link.evidence_link_id, link.document_id)
            )
            continue
        if document.normalized_text[link.char_start : link.char_end] != link.span_text:
            issues.append(
                _issue("span_text_mismatch", link.evidence_link_id, link.span_text)
            )
        if link.target_type == "effect" and link.target_id not in effect_by_id:
            issues.append(
                _issue("missing_effect_target", link.evidence_link_id, link.target_id)
            )
        if link.target_type == "claim" and link.target_id not in claim_by_id:
            issues.append(
                _issue("missing_claim_target", link.evidence_link_id, link.target_id)
            )
        if link.support_label == "supports":
            support_fields.setdefault((link.target_type, link.target_id), set()).add(
                link.support_field
            )

    for effect in effects:
        document = document_by_id.get(effect.document_id)
        if document is None:
            issues.append(
                _issue("missing_effect_document", effect.effect_id, effect.document_id)
            )
            continue
        _validate_provenance(effect, document, issues)
        missing = EFFECT_EVIDENCE_FIELDS - support_fields.get(
            ("effect", effect.effect_id), set()
        )
        if missing:
            issues.append(
                _issue(
                    "formal_effect_missing_field_support",
                    effect.effect_id,
                    ",".join(sorted(missing)),
                )
            )

    for claim in claims:
        document = document_by_id.get(claim.document_id)
        effect = effect_by_id.get(claim.effect_id)
        if document is None:
            issues.append(
                _issue("missing_claim_document", claim.claim_id, claim.document_id)
            )
        else:
            _validate_provenance(claim, document, issues)
        if effect is None:
            issues.append(
                _issue("missing_claim_effect", claim.claim_id, claim.effect_id)
            )
        elif claim.relation_type != RELATION_BY_EFFECT_TYPE[effect.effect_type]:
            issues.append(
                _issue(
                    "claim_relation_type_mismatch", claim.claim_id, claim.relation_type
                )
            )
        required_claim_fields = set(CLAIM_REQUIRED_EVIDENCE_FIELDS)
        if claim.attribution_holder_surface is not None:
            required_claim_fields.add("attribution_holder_surface")
        missing_claim_fields = required_claim_fields - support_fields.get(
            ("claim", claim.claim_id), set()
        )
        if missing_claim_fields:
            issues.append(
                _issue(
                    "formal_claim_missing_field_support",
                    claim.claim_id,
                    ",".join(sorted(missing_claim_fields)),
                )
            )
        if (
            claim.canonical_claim_group_id
            and claim.canonical_claim_group_id not in group_by_id
        ):
            issues.append(
                _issue(
                    "missing_claim_group",
                    claim.claim_id,
                    claim.canonical_claim_group_id,
                )
            )

    for group in claim_groups or []:
        if any(claim_id not in claim_by_id for claim_id in group.claim_ids):
            issues.append(
                _issue(
                    "claim_group_missing_claim",
                    group.canonical_claim_group_id,
                    "unknown claim_id",
                )
            )
        if not any(
            effect.canonical_effect_id == group.canonical_effect_id
            for effect in effects
        ):
            issues.append(
                _issue(
                    "claim_group_missing_effect",
                    group.canonical_claim_group_id,
                    group.canonical_effect_id,
                )
            )

    for pair in claim_pairs or []:
        left = claim_by_id.get(pair.left_claim_id)
        right = claim_by_id.get(pair.right_claim_id)
        if left is None or right is None:
            issues.append(
                _issue(
                    "claim_pair_missing_claim", pair.claim_pair_id, "unknown claim_id"
                )
            )
        elif left.event_id != right.event_id or pair.event_id != left.event_id:
            issues.append(
                _issue("claim_pair_event_mismatch", pair.claim_pair_id, pair.event_id)
            )
    return issues


def assert_valid_cross_file_references(**kwargs) -> None:
    issues = validate_cross_file_references(**kwargs)
    if issues:
        detail = "; ".join(
            f"{row.code}:{row.record_id}:{row.message}" for row in issues
        )
        raise ValueError(detail)


def _unique_index(rows, field: str, issues: list[EAValidationIssue]):
    result = {}
    for row in rows:
        value = getattr(row, field)
        if value in result:
            issues.append(_issue("duplicate_id", value, field))
        result[value] = row
    return result


def _validate_provenance(
    row, document: DocumentRecord, issues: list[EAValidationIssue]
) -> None:
    record_id = getattr(row, "effect_id", None) or row.claim_id
    for field in (
        "event_id",
        "reporting_source_id",
        "primary_source_id",
        "derivation_type",
    ):
        if getattr(row, field) != getattr(document, field):
            issues.append(_issue("provenance_mismatch", record_id, field))


def _issue(code: str, record_id: str, message: str) -> EAValidationIssue:
    return EAValidationIssue(code=code, record_id=str(record_id), message=str(message))
