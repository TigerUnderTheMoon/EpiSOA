"""Conservative automatic Canonical Effect and Claim aggregation."""

from __future__ import annotations

import hashlib
import itertools
import json
import unicodedata
from dataclasses import dataclass

from episoa.ea.matching import chinese_character_f1
from episoa.ea.schema import (
    AttributionClaim,
    CanonicalAdjudicationRecord,
    CanonicalClaimGroup,
    ViewpointEffect,
)


@dataclass(frozen=True)
class CanonicalEffectResult:
    effects: tuple[ViewpointEffect, ...]
    adjudication_queue: tuple[CanonicalAdjudicationRecord, ...]


@dataclass(frozen=True)
class CanonicalClaimResult:
    claims: tuple[AttributionClaim, ...]
    groups: tuple[CanonicalClaimGroup, ...]
    adjudication_queue: tuple[CanonicalAdjudicationRecord, ...]


def aggregate_effects(
    effects: list[ViewpointEffect],
    *,
    ambiguity_threshold: float = 0.5,
) -> CanonicalEffectResult:
    exact_groups: dict[tuple[str, ...], list[ViewpointEffect]] = {}
    for effect in effects:
        exact_groups.setdefault(_effect_key(effect), []).append(effect)

    assigned: list[ViewpointEffect] = []
    for key, rows in sorted(exact_groups.items()):
        canonical_id = _membership_id(
            "ce", rows[0].event_id, [row.effect_id for row in rows]
        )
        assigned.extend(
            row.model_copy(update={"canonical_effect_id": canonical_id}) for row in rows
        )

    queue: list[CanonicalAdjudicationRecord] = []
    for left, right in itertools.combinations(assigned, 2):
        if _effect_ambiguity(left, right, ambiguity_threshold):
            record_ids = sorted([left.effect_id, right.effect_id])
            queue.append(
                CanonicalAdjudicationRecord(
                    adjudication_id=_stable_id("ADJ-EF", record_ids),
                    target_type="effect",
                    event_id=left.event_id,
                    record_ids=record_ids,
                    reason="similar_nonidentical_normalized_effect_key",
                )
            )
    return CanonicalEffectResult(tuple(assigned), tuple(_dedupe_adjudications(queue)))


def aggregate_claims(
    claims: list[AttributionClaim],
    effects: list[ViewpointEffect],
    *,
    ambiguity_threshold: float = 0.5,
) -> CanonicalClaimResult:
    canonical_effect_by_id = {row.effect_id: row.canonical_effect_id for row in effects}
    exact_groups: dict[tuple[str, ...], list[AttributionClaim]] = {}
    for claim in claims:
        canonical_effect_id = canonical_effect_by_id.get(claim.effect_id)
        if not canonical_effect_id:
            raise ValueError(
                f"claim {claim.claim_id} references an Effect without canonical_effect_id"
            )
        exact_groups.setdefault(_claim_key(claim, canonical_effect_id), []).append(
            claim
        )

    assigned: list[AttributionClaim] = []
    groups: list[CanonicalClaimGroup] = []
    for key, rows in sorted(exact_groups.items()):
        group_id = _membership_id(
            "ccg", rows[0].event_id, [row.claim_id for row in rows]
        )
        assigned.extend(
            row.model_copy(update={"canonical_claim_group_id": group_id})
            for row in rows
        )
        groups.append(
            CanonicalClaimGroup(
                canonical_claim_group_id=group_id,
                event_id=key[0],
                canonical_effect_id=key[1],
                relation_type=rows[0].relation_type,
                normalized_explanation=rows[0].normalized_explanation,
                attribution_holder_category=rows[0].attribution_holder_category,
                polarity=rows[0].polarity,
                claim_ids=sorted(row.claim_id for row in rows),
            )
        )

    queue: list[CanonicalAdjudicationRecord] = []
    for left, right in itertools.combinations(assigned, 2):
        if _claim_ambiguity(left, right, canonical_effect_by_id, ambiguity_threshold):
            record_ids = sorted([left.claim_id, right.claim_id])
            queue.append(
                CanonicalAdjudicationRecord(
                    adjudication_id=_stable_id("ADJ-CL", record_ids),
                    target_type="claim",
                    event_id=left.event_id,
                    record_ids=record_ids,
                    reason="similar_nonidentical_normalized_explanation",
                )
            )
    return CanonicalClaimResult(
        tuple(assigned), tuple(groups), tuple(_dedupe_adjudications(queue))
    )


def annotator_document_rows(
    rows: list[ViewpointEffect | AttributionClaim],
) -> list[dict]:
    """Return A/B rows without program-owned Canonical identifiers."""
    result = []
    for row in rows:
        payload = row.model_dump()
        payload.pop("canonical_effect_id", None)
        payload.pop("canonical_claim_group_id", None)
        result.append(payload)
    return result


def c_adjudication_rows(rows: list[CanonicalAdjudicationRecord]) -> list[dict]:
    """Return only unresolved Canonical cases for annotator C."""
    return [row.model_dump() for row in rows if row.status == "needs_adjudication"]


def normalize_phrase(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(
        char
        for char in text
        if not char.isspace()
        and not unicodedata.category(char).startswith(("P", "S", "Z"))
    )


def _effect_key(effect: ViewpointEffect) -> tuple[str, ...]:
    return (
        effect.event_id,
        effect.stakeholder_category,
        effect.effect_type,
        normalize_phrase(effect.effect_value),
        normalize_phrase(effect.target),
    )


def _claim_key(claim: AttributionClaim, canonical_effect_id: str) -> tuple[str, ...]:
    return (
        claim.event_id,
        canonical_effect_id,
        claim.relation_type,
        normalize_phrase(claim.normalized_explanation),
        claim.attribution_holder_category,
        claim.polarity,
    )


def _effect_ambiguity(
    left: ViewpointEffect, right: ViewpointEffect, threshold: float
) -> bool:
    if left.canonical_effect_id == right.canonical_effect_id:
        return False
    if (
        left.event_id,
        left.stakeholder_category,
        left.effect_type,
    ) != (
        right.event_id,
        right.stakeholder_category,
        right.effect_type,
    ):
        return False
    left_target = normalize_phrase(left.target)
    right_target = normalize_phrase(right.target)
    target_score = chinese_character_f1(left_target, right_target)
    if left.effect_type != "action":
        if normalize_phrase(left.effect_value) != normalize_phrase(right.effect_value):
            return False
        return target_score >= threshold
    left_value = normalize_phrase(left.effect_value)
    right_value = normalize_phrase(right.effect_value)
    value_score = chinese_character_f1(left_value, right_value)
    if left_target == right_target:
        return value_score >= threshold
    if left_value == right_value:
        return target_score >= threshold
    return target_score >= threshold and value_score >= threshold


def _claim_ambiguity(
    left: AttributionClaim,
    right: AttributionClaim,
    canonical_effect_by_id: dict[str, str | None],
    threshold: float,
) -> bool:
    if left.canonical_claim_group_id == right.canonical_claim_group_id:
        return False
    if (
        left.event_id,
        canonical_effect_by_id.get(left.effect_id),
        left.relation_type,
        left.attribution_holder_category,
        left.polarity,
    ) != (
        right.event_id,
        canonical_effect_by_id.get(right.effect_id),
        right.relation_type,
        right.attribution_holder_category,
        right.polarity,
    ):
        return False
    score = chinese_character_f1(
        normalize_phrase(left.normalized_explanation),
        normalize_phrase(right.normalized_explanation),
    )
    return score >= threshold


def _stable_id(prefix: str, value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _membership_id(prefix: str, event_id: str, member_ids: list[str]) -> str:
    payload = event_id + "\n" + "\n".join(sorted(member_ids))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _dedupe_adjudications(
    rows: list[CanonicalAdjudicationRecord],
) -> list[CanonicalAdjudicationRecord]:
    return list({row.adjudication_id: row for row in rows}.values())
