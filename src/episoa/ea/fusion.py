"""Attribution-Preserving Canonical Fusion (APCF)."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Literal

from episoa.ea.canonical import normalize_phrase
from episoa.ea.schema import (
    AttributionClaim,
    CanonicalAdjudicationRecord,
    CanonicalClaimGroup,
    CanonicalEffect,
    ClaimPairRelationRecord,
    DocumentRecord,
    FusionClusterDiagnosticRecord,
    FusionPairJudgmentRecord,
    SemanticPairJudgmentRecord,
    ViewpointEffect,
)

FusionMethod = Literal["exact", "embedding", "llm", "apcf"]
DEPENDENT_DERIVATIONS = {
    "official_republication",
    "syndicated_copy",
    "quoted_from_other_source",
}
FUSION_RULE_VERSION = "apcf-v1.5"


@dataclass(frozen=True)
class FusionResult:
    canonical_effects: tuple[CanonicalEffect, ...]
    canonical_claim_groups: tuple[CanonicalClaimGroup, ...]
    claim_pair_relations: tuple[ClaimPairRelationRecord, ...]
    pair_judgments: tuple[FusionPairJudgmentRecord, ...]
    cluster_diagnostics: tuple[FusionClusterDiagnosticRecord, ...]
    adjudication_queue: tuple[CanonicalAdjudicationRecord, ...]
    effect_membership: dict[str, str]
    claim_membership: dict[str, str]


def run_fusion(
    *,
    effects: list[ViewpointEffect],
    claims: list[AttributionClaim],
    documents: list[DocumentRecord],
    method: FusionMethod,
    semantic_judgments: list[SemanticPairJudgmentRecord] | None = None,
    embedding_threshold: float = 0.8,
) -> FusionResult:
    """Fuse verified source records without mutating those records."""
    if method not in {"exact", "embedding", "llm", "apcf"}:
        raise ValueError(f"unknown fusion method: {method}")
    effect_by_id = _unique(effects, "effect_id")
    claim_by_id = _unique(claims, "claim_id")
    document_by_id = _unique(documents, "document_id")
    for effect in effects:
        if effect.document_id not in document_by_id:
            raise ValueError(f"{effect.effect_id}: missing Document")
    for claim in claims:
        if claim.effect_id not in effect_by_id:
            raise ValueError(f"{claim.claim_id}: missing source-level Effect")
        if claim.document_id not in document_by_id:
            raise ValueError(f"{claim.claim_id}: missing Document")

    resource = _judgment_index(semantic_judgments or [])
    effect_pairs = effect_candidate_pairs(effects)
    effect_pair_rows = _effect_pair_decisions(
        effect_pairs,
        effect_by_id,
        method=method,
        resource=resource,
        embedding_threshold=embedding_threshold,
    )
    effect_clusters, effect_diagnostics = _cluster_records(
        sorted(effect_by_id), effect_pair_rows, target_type="effect", method=method
    )
    canonical_effects = _materialize_effects(
        effect_clusters, effect_by_id, document_by_id
    )
    effect_membership = {
        member: row.canonical_effect_id
        for row in canonical_effects
        for member in row.member_effect_ids
    }

    claim_pairs = claim_candidate_pairs(claims)
    claim_pair_rows = _claim_pair_decisions(
        claim_pairs,
        claim_by_id,
        effect_membership,
        method=method,
        resource=resource,
        embedding_threshold=embedding_threshold,
    )
    claim_clusters, claim_diagnostics = _cluster_records(
        sorted(claim_by_id), claim_pair_rows, target_type="claim", method=method
    )
    canonical_claims = _materialize_claims(
        claim_clusters, claim_by_id, effect_membership, document_by_id
    )
    claim_membership = {
        member: row.canonical_claim_group_id
        for row in canonical_claims
        for member in row.claim_ids
    }
    claim_relations = _materialize_claim_pair_relations(
        claim_pair_rows, claim_by_id, claim_membership
    )
    all_pairs = tuple(sorted((*effect_pair_rows, *claim_pair_rows), key=lambda x: x.pair_id))
    queue = tuple(
        CanonicalAdjudicationRecord(
            adjudication_id=_stable_id("adj", row.pair_id),
            target_type=row.target_type,
            event_id=row.event_id,
            record_ids=[row.left_id, row.right_id],
            reason=";".join(row.reason_codes) or "fusion_pair_needs_adjudication",
        )
        for row in all_pairs
        if row.merge_decision == "needs_adjudication"
    )
    return FusionResult(
        tuple(canonical_effects),
        tuple(canonical_claims),
        tuple(claim_relations),
        all_pairs,
        (*effect_diagnostics, *claim_diagnostics),
        queue,
        effect_membership,
        claim_membership,
    )


def effect_candidate_pairs(effects: list[ViewpointEffect]) -> list[tuple[str, str]]:
    """Broad same-event universe; Stage and open Action semantics never block here."""
    rows = sorted(effects, key=lambda row: row.effect_id)
    pairs = []
    for left, right in itertools.combinations(rows, 2):
        if left.event_id != right.event_id:
            continue
        if left.stakeholder_category != right.stakeholder_category:
            continue
        if left.effect_type != right.effect_type:
            continue
        if left.effect_type != "action" and normalize_phrase(
            left.effect_value
        ) != normalize_phrase(right.effect_value):
            continue
        pairs.append((left.effect_id, right.effect_id))
    return pairs


def claim_candidate_pairs(
    claims: list[AttributionClaim], effect_membership: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Fixed Claim pair universe; predicted Effect clusters cannot alter candidates."""
    del effect_membership  # retained for compatibility with earlier callers
    rows = sorted(claims, key=lambda row: row.claim_id)
    pairs = []
    for left, right in itertools.combinations(rows, 2):
        if left.event_id != right.event_id:
            continue
        if left.primary_source_id == right.primary_source_id:
            continue
        if left.relation_type != right.relation_type:
            continue
        pairs.append((left.claim_id, right.claim_id))
    return pairs


def make_pair_id(target_type: str, left_id: str, right_id: str) -> str:
    left_id, right_id = sorted((left_id, right_id))
    return _stable_id(f"pair-{target_type}", (left_id, right_id))


def _effect_pair_decisions(
    pairs,
    records,
    *,
    method,
    resource,
    embedding_threshold,
) -> list[FusionPairJudgmentRecord]:
    output = []
    for left_id, right_id in pairs:
        left, right = records[left_id], records[right_id]
        semantic = _semantic_for_pair(
            "effect",
            left_id,
            right_id,
            left.event_id,
            resource,
            left,
            right,
            allow_exact_fallback=method == "exact",
        )
        constraints = {
            "event_exact": left.event_id == right.event_id,
            "stakeholder_category_exact": left.stakeholder_category
            == right.stakeholder_category,
            "effect_type_exact": left.effect_type == right.effect_type,
            "closed_effect_value_exact": left.effect_type == "action"
            or normalize_phrase(left.effect_value) == normalize_phrase(right.effect_value),
        }
        decision, reasons = _effect_merge_decision(
            semantic, constraints, method, embedding_threshold
        )
        output.append(_fusion_row(semantic, decision, constraints, reasons))
    return output


def _claim_pair_decisions(
    pairs,
    records,
    effect_membership,
    *,
    method,
    resource,
    embedding_threshold,
) -> list[FusionPairJudgmentRecord]:
    output = []
    for left_id, right_id in pairs:
        left, right = records[left_id], records[right_id]
        semantic = _semantic_for_pair(
            "claim",
            left_id,
            right_id,
            left.event_id,
            resource,
            left,
            right,
            allow_exact_fallback=method == "exact",
        )
        known_left = left.attribution_holder_category != "other_or_unknown"
        known_right = right.attribution_holder_category != "other_or_unknown"
        constraints = {
            "event_exact": left.event_id == right.event_id,
            "canonical_effect_exact": effect_membership[left.effect_id]
            == effect_membership[right.effect_id],
            "relation_type_exact": left.relation_type == right.relation_type,
            "polarity_exact": left.polarity == right.polarity,
            "attribution_holder_exact": left.attribution_holder_category
            == right.attribution_holder_category,
            "attribution_holder_knownness_exact": known_left == known_right,
        }
        decision, reasons = _claim_merge_decision(
            semantic, constraints, method, embedding_threshold
        )
        output.append(_fusion_row(semantic, decision, constraints, reasons))
    return output


def _semantic_for_pair(
    target_type,
    left_id,
    right_id,
    event_id,
    resource,
    left,
    right,
    *,
    allow_exact_fallback,
) -> SemanticPairJudgmentRecord:
    pair_id = make_pair_id(target_type, left_id, right_id)
    if pair_id in resource:
        row = resource[pair_id]
        if (row.target_type, row.event_id, row.left_id, row.right_id) != (
            target_type,
            event_id,
            left_id,
            right_id,
        ):
            raise ValueError(f"semantic judgment provenance mismatch: {pair_id}")
        return row
    if not allow_exact_fallback:
        resource_ids = {row.judgment_resource_id for row in resource.values()}
        return SemanticPairJudgmentRecord(
            pair_id=pair_id,
            target_type=target_type,
            event_id=event_id,
            left_id=left_id,
            right_id=right_id,
            semantic_label="unresolved",
            judgment_resource_id=next(iter(resource_ids), "missing-resource"),
            model_version="missing",
            prompt_version="missing",
            decoding_version="missing",
        )
    if target_type == "effect":
        equivalent = (
            normalize_phrase(left.effect_value) == normalize_phrase(right.effect_value)
            and normalize_phrase(left.target) == normalize_phrase(right.target)
        )
        label = "equivalent_effect" if equivalent else "unresolved"
    else:
        equivalent = normalize_phrase(left.normalized_explanation) == normalize_phrase(
            right.normalized_explanation
        )
        label = "equivalent_explanation" if equivalent else "unresolved"
    return SemanticPairJudgmentRecord(
        pair_id=pair_id,
        target_type=target_type,
        event_id=event_id,
        left_id=left_id,
        right_id=right_id,
        semantic_label=label,
        semantic_score=1.0 if equivalent else None,
        judgment_resource_id="deterministic-exact-v1",
        model_version="none",
        prompt_version="none",
        decoding_version="none",
    )


def _effect_merge_decision(semantic, constraints, method, threshold):
    failed = [name for name, passed in constraints.items() if not passed]
    if failed or semantic.temporal_compatibility == "conflict":
        return "cannot_link", [*failed, "temporal_conflict"] if semantic.temporal_compatibility == "conflict" else failed
    if semantic.temporal_compatibility == "uncertain":
        return "needs_adjudication", ["temporal_uncertain"]
    equivalent = semantic.semantic_label == "equivalent_effect"
    if method == "embedding":
        if semantic.semantic_score is None:
            raise ValueError(f"embedding score missing for {semantic.pair_id}")
        equivalent = semantic.semantic_score >= threshold
    if equivalent:
        return "must_link", []
    if semantic.semantic_label in {"distinct_effect"}:
        return "cannot_link", ["semantic_distinct"]
    return "needs_adjudication", ["semantic_unresolved"]


def _claim_merge_decision(semantic, constraints, method, threshold):
    for key in ("event_exact", "canonical_effect_exact", "relation_type_exact", "polarity_exact"):
        if not constraints[key]:
            return "cannot_link", [key]
    if not constraints["attribution_holder_knownness_exact"]:
        return "needs_adjudication", ["attribution_holder_knownness_mismatch"]
    if not constraints["attribution_holder_exact"]:
        return "cannot_link", ["attribution_holder_mismatch"]
    if semantic.temporal_compatibility == "conflict":
        return "cannot_link", ["temporal_conflict"]
    if semantic.temporal_compatibility == "uncertain":
        return "needs_adjudication", ["temporal_uncertain"]
    equivalent = semantic.semantic_label == "equivalent_explanation"
    if method == "embedding":
        if semantic.semantic_score is None:
            raise ValueError(f"embedding score missing for {semantic.pair_id}")
        equivalent = semantic.semantic_score >= threshold
    if equivalent:
        return "must_link", []
    if semantic.semantic_label in {"additional", "explicitly_contradicted"}:
        return "cannot_link", [f"semantic_{semantic.semantic_label}"]
    return "needs_adjudication", ["semantic_unresolved"]


def _fusion_row(semantic, decision, constraints, reasons):
    return FusionPairJudgmentRecord(
        **semantic.model_dump(),
        merge_decision=decision,
        constraint_results=constraints,
        reason_codes=sorted(set(reasons)),
        rule_version=FUSION_RULE_VERSION,
    )


def _cluster_records(ids, pairs, *, target_type, method):
    pair_by_members = {(row.left_id, row.right_id): row for row in pairs}
    clusters = [{record_id} for record_id in ids]
    diagnostics = []
    if method == "exact":
        allowed = [row for row in pairs if row.merge_decision == "must_link"]
        return _union_components(clusters, allowed), diagnostics
    if method == "llm":
        allowed = [
            row
            for row in pairs
            if row.semantic_label
            in {"equivalent_effect", "equivalent_explanation"}
            and row.temporal_compatibility == "compatible"
            and all(
                row.constraint_results.get(key, True)
                for key in (
                    "event_exact",
                    "stakeholder_category_exact",
                    "effect_type_exact",
                    "closed_effect_value_exact",
                    "canonical_effect_exact",
                    "relation_type_exact",
                    "polarity_exact",
                )
            )
        ]
        return _union_components(clusters, allowed), diagnostics

    for trigger in sorted(
        (row for row in pairs if row.merge_decision == "must_link"),
        key=lambda row: row.pair_id,
    ):
        left_cluster = next(group for group in clusters if trigger.left_id in group)
        right_cluster = next(group for group in clusters if trigger.right_id in group)
        if left_cluster is right_cluster:
            continue
        cross_rows = []
        missing = []
        for left_id, right_id in itertools.product(
            sorted(left_cluster), sorted(right_cluster)
        ):
            key = tuple(sorted((left_id, right_id)))
            row = pair_by_members.get(key)
            if row is None:
                missing.append(key)
            else:
                cross_rows.append(row)
        if missing:
            decision = "needs_adjudication"
            reasons = ["missing_cross_cluster_pair"]
        elif any(row.merge_decision == "cannot_link" for row in cross_rows):
            decision = "cannot_link"
            reasons = ["cross_cluster_cannot_link"]
        elif any(row.merge_decision != "must_link" for row in cross_rows):
            decision = "needs_adjudication"
            reasons = ["cross_cluster_needs_adjudication"]
        else:
            decision = "must_link"
            reasons = []
        diagnostics.append(
            FusionClusterDiagnosticRecord(
                diagnostic_id=_stable_id(
                    "cluster", (target_type, sorted(left_cluster), sorted(right_cluster))
                ),
                target_type=target_type,
                event_id=trigger.event_id,
                left_cluster_ids=sorted(left_cluster),
                right_cluster_ids=sorted(right_cluster),
                decision=decision,
                blocking_pair_ids=sorted(row.pair_id for row in cross_rows if row.merge_decision != "must_link"),
                reason_codes=reasons,
            )
        )
        if decision == "must_link":
            merged = left_cluster | right_cluster
            clusters = [
                group for group in clusters if group is not left_cluster and group is not right_cluster
            ]
            clusters.append(merged)
    return sorted(clusters, key=lambda group: sorted(group)), diagnostics


def _union_components(clusters, allowed):
    for row in sorted(allowed, key=lambda item: item.pair_id):
        left = next(group for group in clusters if row.left_id in group)
        right = next(group for group in clusters if row.right_id in group)
        if left is right:
            continue
        merged = left | right
        clusters = [group for group in clusters if group is not left and group is not right]
        clusters.append(merged)
    return sorted(clusters, key=lambda group: sorted(group))


def _materialize_effects(clusters, records, documents):
    output = []
    for cluster in clusters:
        members = sorted(cluster)
        rows = [records[member] for member in members]
        event_id = rows[0].event_id
        counts = lineage_multiplicities(rows, documents)
        output.append(
            CanonicalEffect(
                canonical_effect_id=membership_id("ce", event_id, members),
                event_id=event_id,
                stakeholder_category=rows[0].stakeholder_category,
                effect_type=rows[0].effect_type,
                normalized_effect_value=min(normalize_phrase(row.effect_value) for row in rows),
                normalized_target=min(normalize_phrase(row.target) for row in rows),
                member_effect_ids=members,
                observed_stages=sorted({row.effect_stage for row in rows}),
                **counts,
            )
        )
    return sorted(output, key=lambda row: row.canonical_effect_id)


def _materialize_claims(clusters, records, effect_membership, documents):
    output = []
    for cluster in clusters:
        members = sorted(cluster)
        rows = [records[member] for member in members]
        effect_ids = {effect_membership[row.effect_id] for row in rows}
        if len(effect_ids) != 1:
            raise ValueError("Canonical Claim cluster spans Canonical Effects")
        counts = lineage_multiplicities(rows, documents)
        output.append(
            CanonicalClaimGroup(
                canonical_claim_group_id=membership_id("ccg", rows[0].event_id, members),
                event_id=rows[0].event_id,
                canonical_effect_id=next(iter(effect_ids)),
                relation_type=rows[0].relation_type,
                normalized_explanation=min(normalize_phrase(row.normalized_explanation) for row in rows),
                attribution_holder_category=rows[0].attribution_holder_category,
                polarity=rows[0].polarity,
                claim_ids=members,
                **counts,
            )
        )
    return sorted(output, key=lambda row: row.canonical_claim_group_id)


def _materialize_claim_pair_relations(pair_rows, claims, membership):
    output = []
    for row in pair_rows:
        if row.semantic_label not in {
            "equivalent_explanation",
            "additional",
            "explicitly_contradicted",
            "unresolved",
        }:
            continue
        if membership[row.left_id] == membership[row.right_id]:
            continue
        left, right = claims[row.left_id], claims[row.right_id]
        if left.primary_source_id == right.primary_source_id:
            continue
        output.append(
            ClaimPairRelationRecord(
                claim_pair_id=_stable_id("claim-rel", row.pair_id),
                event_id=row.event_id,
                left_claim_id=row.left_id,
                right_claim_id=row.right_id,
                left_primary_source_id=left.primary_source_id,
                right_primary_source_id=right.primary_source_id,
                relation=row.semantic_label,
            )
        )
    return sorted(output, key=lambda row: row.claim_pair_id)


def lineage_multiplicities(rows, documents):
    document_rows = [documents[row.document_id] for row in rows]
    known = [row for row in document_rows if row.derivation_type != "unknown"]
    return {
        "document_multiplicity": len({row.document_id for row in document_rows}),
        "primary_source_multiplicity": len({row.primary_source_id for row in known}),
        "dependent_reproduction_count": sum(
            row.derivation_type in DEPENDENT_DERIVATIONS for row in document_rows
        ),
        "unknown_lineage_count": sum(
            row.derivation_type == "unknown" for row in document_rows
        ),
    }


def membership_id(prefix: Literal["ce", "ccg"], event_id: str, member_ids: list[str]) -> str:
    payload = event_id + "\n" + "\n".join(sorted(member_ids))
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _judgment_index(rows):
    output = {}
    resource_ids = {row.judgment_resource_id for row in rows}
    if len(resource_ids) > 1:
        raise ValueError("one fusion run must use exactly one semantic judgment resource")
    for row in rows:
        if row.pair_id in output:
            raise ValueError(f"duplicate semantic pair judgment: {row.pair_id}")
        output[row.pair_id] = row
    return output


def _unique(rows, field):
    output = {}
    for row in rows:
        key = getattr(row, field)
        if key in output:
            raise ValueError(f"duplicate {field}: {key}")
        output[key] = row
    return output


def _stable_id(prefix, value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}"
