"""Four-level APCF evaluation and method-applicability contracts."""

from __future__ import annotations

import itertools
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from episoa.ea.schema import (
    AttributionClaim,
    CanonicalClaimGroup,
    ClaimPairRelationRecord,
)

FusionEvaluationLevel = Literal[
    "effect_fusion",
    "claim_fusion_oracle",
    "full_fusion",
    "end_to_end",
]
FusionMethodId = Literal["exact", "embedding", "llm_pairwise", "apcf"]


class FusionMethodRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_id: FusionMethodId
    candidate_set_hash: str = Field(..., min_length=1)
    normalization_version: str = Field(..., min_length=1)
    gold_version: str = Field(..., min_length=1)
    judgment_resource_id: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    prompt_version: str = Field(..., min_length=1)
    decoding_version: str = Field(..., min_length=1)
    temperature: float = Field(default=0.0, ge=0.0)
    token_budget: int = Field(default=0, ge=0)
    failure_policy: str = Field(
        default="unresolved_or_capacity_failure_is_reported_not_silently_scored",
        min_length=1,
    )


class FusionComparisonManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[FusionMethodRunSpec] = Field(..., min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_shared_resources(self) -> FusionComparisonManifest:
        if {row.method_id for row in self.runs} != {
            "exact",
            "embedding",
            "llm_pairwise",
            "apcf",
        }:
            raise ValueError("fusion comparison requires all four frozen methods")
        for field in ("candidate_set_hash", "normalization_version", "gold_version"):
            if len({getattr(row, field) for row in self.runs}) != 1:
                raise ValueError(f"all fusion methods must share {field}")
        llm = {row.method_id: row for row in self.runs}
        for field in (
            "judgment_resource_id",
            "model_version",
            "prompt_version",
            "decoding_version",
            "temperature",
            "token_budget",
            "failure_policy",
        ):
            if getattr(llm["llm_pairwise"], field) != getattr(llm["apcf"], field):
                raise ValueError(f"LLM Pairwise and APCF must share {field}")
        return self


def canonicalization_metrics(
    gold_membership: dict[str, str],
    predicted_membership: dict[str, str],
    *,
    excluded_pairs: set[tuple[str, str]] | None = None,
) -> dict[str, float | int]:
    if set(gold_membership) != set(predicted_membership):
        raise ValueError("Gold and prediction must cover the same source records")
    excluded = {tuple(sorted(pair)) for pair in (excluded_pairs or set())}
    ids = sorted(gold_membership)
    gold_same = set()
    pred_same = set()
    scored_pairs = 0
    for pair in itertools.combinations(ids, 2):
        if pair in excluded:
            continue
        scored_pairs += 1
        if gold_membership[pair[0]] == gold_membership[pair[1]]:
            gold_same.add(pair)
        if predicted_membership[pair[0]] == predicted_membership[pair[1]]:
            pred_same.add(pair)
    tp = len(gold_same & pred_same)
    fp = len(pred_same - gold_same)
    fn = len(gold_same - pred_same)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive_pairs": tp,
        "false_merge_pairs": fp,
        "false_split_pairs": fn,
        "scored_pairs": scored_pairs,
        "excluded_pairs": len(excluded),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "false_merge_rate": round(fp / len(pred_same), 6) if pred_same else 0.0,
        "false_split_rate": round(fn / len(gold_same), 6) if gold_same else 0.0,
    }


def attribution_collapse_rate(
    claims: list[AttributionClaim], predicted_membership: dict[str, str]
) -> dict[str, float | int]:
    by_group: dict[str, list[AttributionClaim]] = {}
    for claim in claims:
        by_group.setdefault(predicted_membership[claim.claim_id], []).append(claim)
    collapsed_pairs = total_pairs = 0
    for rows in by_group.values():
        for left, right in itertools.combinations(rows, 2):
            total_pairs += 1
            collapsed_pairs += (
                left.attribution_holder_category != right.attribution_holder_category
            )
    return {
        "collapsed_attribution_pairs": collapsed_pairs,
        "within_cluster_pairs": total_pairs,
        "rate": round(collapsed_pairs / total_pairs, 6) if total_pairs else 0.0,
    }


def conflict_preservation_rate(
    gold_relations: list[ClaimPairRelationRecord],
    predicted_membership: dict[str, str],
    *,
    minimum_for_gate: int = 5,
) -> dict[str, float | int | str | None]:
    contradictions = [
        row for row in gold_relations if row.relation == "explicitly_contradicted"
    ]
    preserved = sum(
        predicted_membership[row.left_claim_id]
        != predicted_membership[row.right_claim_id]
        for row in contradictions
    )
    rate = preserved / len(contradictions) if contradictions else None
    return {
        "preserved": preserved,
        "gold_contradiction_pairs": len(contradictions),
        "rate": round(rate, 6) if rate is not None else None,
        "gate_status": "eligible"
        if len(contradictions) >= minimum_for_gate
        else "NA",
    }


def source_independence_overcount_rate(
    groups: list[CanonicalClaimGroup],
) -> dict[str, float | int]:
    document_total = sum(row.document_multiplicity for row in groups)
    lineage_total = sum(row.primary_source_multiplicity for row in groups)
    overcount = max(document_total - lineage_total, 0)
    return {
        "document_supports": document_total,
        "primary_source_lineages": lineage_total,
        "overcount": overcount,
        "rate": round(overcount / document_total, 6) if document_total else 0.0,
    }


def evaluate_fusion_level(
    level: FusionEvaluationLevel,
    *,
    gold_membership: dict[str, str],
    predicted_membership: dict[str, str],
    claims: list[AttributionClaim] | None = None,
    gold_relations: list[ClaimPairRelationRecord] | None = None,
    predicted_groups: list[CanonicalClaimGroup] | None = None,
    excluded_pairs: set[tuple[str, str]] | None = None,
) -> dict:
    result = {
        "evaluation_level": level,
        "canonicalization": canonicalization_metrics(
            gold_membership,
            predicted_membership,
            excluded_pairs=excluded_pairs,
        ),
    }
    if claims is not None:
        result["attribution_collapse"] = attribution_collapse_rate(
            claims, predicted_membership
        )
    if gold_relations is not None:
        result["conflict_preservation"] = conflict_preservation_rate(
            gold_relations, predicted_membership
        )
    if predicted_groups is not None:
        result["source_independence_overcount"] = (
            source_independence_overcount_rate(predicted_groups)
        )
    return result
