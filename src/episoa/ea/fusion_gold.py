"""Method-neutral A/B/C Fusion Gold and blocking-recall audit."""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from episoa.data.loader import read_typed_jsonl, write_jsonl
from episoa.ea.fusion import effect_candidate_pairs, make_pair_id
from episoa.ea.schema import (
    AttributionClaim,
    FusionSemanticLabel,
    FusionTargetType,
    ViewpointEffect,
)


class FusionPairSheetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str = Field(..., min_length=1)
    target_type: FusionTargetType
    event_id: str = Field(..., min_length=1)
    left_id: str = Field(..., min_length=1)
    right_id: str = Field(..., min_length=1)
    semantic_label: FusionSemanticLabel | None = None
    annotator_id: str | None = None

    @model_validator(mode="after")
    def validate_pair(self) -> FusionPairSheetRecord:
        if self.left_id >= self.right_id:
            raise ValueError("Fusion Gold pair IDs must be sorted")
        return self


class BlockerFreezeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocker_version: str = Field(..., min_length=1)
    pair_universe_hash: str = Field(..., min_length=1)
    effect_blocking_recall: float = Field(..., ge=0.0, le=1.0)
    claim_blocking_recall: float = Field(..., ge=0.0, le=1.0)
    threshold: float = Field(default=0.98, ge=0.0, le=1.0)
    frozen_before_formal_inference: bool
    formal_results_seen: bool = False

    @model_validator(mode="after")
    def validate_freeze(self) -> BlockerFreezeManifest:
        if self.formal_results_seen:
            raise ValueError("blocker cannot be frozen after Formal results are seen")
        if min(self.effect_blocking_recall, self.claim_blocking_recall) < self.threshold:
            raise ValueError("blocking recall is below the preregistered threshold")
        if not self.frozen_before_formal_inference:
            raise ValueError("blocker must be frozen before Formal inference")
        return self


def initialize_fusion_gold_workspace(
    root: str | Path,
    *,
    effects: list[ViewpointEffect],
    claims: list[AttributionClaim],
) -> dict[str, object]:
    """Create near-exhaustive Pilot pair sheets without invoking APCF."""
    root = Path(root)
    effect_by_id = {row.effect_id: row for row in effects}
    claim_by_id = {row.claim_id: row for row in claims}
    rows = []
    for left_id, right_id in effect_candidate_pairs(effects):
        rows.append(
            FusionPairSheetRecord(
                pair_id=make_pair_id("effect", left_id, right_id),
                target_type="effect",
                event_id=effect_by_id[left_id].event_id,
                left_id=left_id,
                right_id=right_id,
            )
        )
    for left_id, right_id in _claim_gold_pair_universe(claims):
        rows.append(
            FusionPairSheetRecord(
                pair_id=make_pair_id("claim", left_id, right_id),
                target_type="claim",
                event_id=claim_by_id[left_id].event_id,
                left_id=left_id,
                right_id=right_id,
            )
        )
    rows.sort(key=lambda row: row.pair_id)
    for annotator in ("A", "B"):
        write_jsonl(
            root / f"annotator_{annotator}" / "fusion_pair_annotations.jsonl",
            [row.model_copy(update={"annotator_id": annotator}) for row in rows],
        )
    write_jsonl(root / "annotator_C" / "fusion_pair_disagreements.jsonl", [])
    return {
        "status": "fusion_gold_initialized",
        "pair_count": len(rows),
        "effect_pair_count": sum(row.target_type == "effect" for row in rows),
        "claim_pair_count": sum(row.target_type == "claim" for row in rows),
        "apcf_invoked": False,
        "canonical_prediction_consumed": False,
    }


def _claim_gold_pair_universe(
    claims: list[AttributionClaim],
) -> list[tuple[str, str]]:
    """Near-exhaustive cross-lineage Claim universe without predicted clusters."""
    rows = sorted(claims, key=lambda row: row.claim_id)
    return [
        (left.claim_id, right.claim_id)
        for left, right in itertools.combinations(rows, 2)
        if left.event_id == right.event_id
        and left.primary_source_id != right.primary_source_id
    ]


def build_fusion_gold_disagreements(root: str | Path) -> dict[str, object]:
    root = Path(root)
    a_rows = read_typed_jsonl(
        root / "annotator_A" / "fusion_pair_annotations.jsonl", FusionPairSheetRecord
    )
    b_rows = read_typed_jsonl(
        root / "annotator_B" / "fusion_pair_annotations.jsonl", FusionPairSheetRecord
    )
    a_by_id = _index_complete_annotations(a_rows, "A")
    b_by_id = _index_complete_annotations(b_rows, "B")
    if set(a_by_id) != set(b_by_id):
        raise ValueError("A/B Fusion Gold pair universes differ")
    disagreements = []
    for pair_id in sorted(a_by_id):
        left, right = a_by_id[pair_id], b_by_id[pair_id]
        if left.semantic_label != right.semantic_label:
            disagreements.append(
                left.model_copy(update={"semantic_label": None, "annotator_id": "C"})
            )
    write_jsonl(
        root / "annotator_C" / "fusion_pair_disagreements.jsonl", disagreements
    )
    return {
        "status": "fusion_gold_disagreements_ready",
        "pair_count": len(a_rows),
        "disagreement_count": len(disagreements),
    }


def export_fusion_gold(
    root: str | Path,
    *,
    blocked_pair_ids: set[str],
    threshold: float = 0.98,
) -> dict[str, object]:
    root = Path(root)
    a_rows = _index_complete_annotations(
        read_typed_jsonl(
            root / "annotator_A" / "fusion_pair_annotations.jsonl",
            FusionPairSheetRecord,
        ),
        "A",
    )
    b_rows = _index_complete_annotations(
        read_typed_jsonl(
            root / "annotator_B" / "fusion_pair_annotations.jsonl",
            FusionPairSheetRecord,
        ),
        "B",
    )
    c_path = root / "annotator_C" / "fusion_pair_disagreements.jsonl"
    c_rows = _index_complete_annotations(
        read_typed_jsonl(c_path, FusionPairSheetRecord), "C"
    ) if c_path.is_file() else {}
    gold = []
    for pair_id in sorted(a_rows):
        if pair_id not in b_rows:
            raise ValueError("A/B Fusion Gold pair universes differ")
        if a_rows[pair_id].semantic_label == b_rows[pair_id].semantic_label:
            label = a_rows[pair_id].semantic_label
        else:
            if pair_id not in c_rows:
                raise ValueError(f"unresolved Fusion Gold disagreement: {pair_id}")
            label = c_rows[pair_id].semantic_label
        gold.append(a_rows[pair_id].model_copy(update={"semantic_label": label, "annotator_id": "Gold"}))
    metrics = blocking_recall(gold, blocked_pair_ids)
    if min(metrics["effect"]["recall"], metrics["claim"]["recall"]) < threshold:
        raise ValueError("Candidate Blocking Recall is below the preregistered threshold")
    write_jsonl(root / "gold" / "fusion_gold_pairs.jsonl", gold)
    payload = "\n".join(row.pair_id for row in gold)
    return {
        "status": "fusion_gold_exported",
        "pair_count": len(gold),
        "blocking_recall": metrics,
        "pair_universe_hash": "sha256:"
        + hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "apcf_invoked": False,
    }


def blocking_recall(
    gold_pairs: list[FusionPairSheetRecord], blocked_pair_ids: set[str]
) -> dict[str, dict[str, float | int]]:
    equivalent_by_type = {
        "effect": {
            row.pair_id
            for row in gold_pairs
            if row.target_type == "effect"
            and row.semantic_label == "equivalent_effect"
        },
        "claim": {
            row.pair_id
            for row in gold_pairs
            if row.target_type == "claim"
            and row.semantic_label == "equivalent_explanation"
        },
    }
    output = {}
    for target_type, gold_ids in equivalent_by_type.items():
        covered = len(gold_ids & blocked_pair_ids)
        output[target_type] = {
            "covered_equivalent_pairs": covered,
            "gold_equivalent_pairs": len(gold_ids),
            "recall": round(covered / len(gold_ids), 6) if gold_ids else 1.0,
        }
    return output


def _index_complete_annotations(rows, annotator_id):
    output = {}
    for row in rows:
        if row.annotator_id != annotator_id:
            raise ValueError(f"row {row.pair_id} is not owned by annotator {annotator_id}")
        if row.semantic_label is None:
            raise ValueError(f"annotator {annotator_id} left {row.pair_id} unlabeled")
        if row.pair_id in output:
            raise ValueError(f"duplicate pair annotation: {row.pair_id}")
        output[row.pair_id] = row
    return output
