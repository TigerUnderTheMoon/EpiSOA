"""Executable A/B/C Gold workflow for document-level EA annotations."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from episoa.data.loader import write_jsonl
from episoa.ea.canonical import aggregate_claims, aggregate_effects
from episoa.ea.schema import (
    AttributionClaim,
    CanonicalAdjudicationRecord,
    CanonicalClaimGroup,
    DocumentRecord,
    EvidenceLink,
    SourceRecord,
    ViewpointEffect,
)
from episoa.ea.validation import assert_valid_cross_file_references

ItemType = Literal["effect", "claim", "evidence"]
ANNOTATION_FIELDS = (
    "annotation_key",
    "item_type",
    "record_id",
    "document_id",
    "candidate_origin",
    "candidate_payload_json",
    "human_decision",
    "human_payload_json",
    "review_status",
    "annotator_id",
    "notes",
)
C_DISAGREEMENT_FIELDS = (
    "annotation_key",
    "item_type",
    "record_id",
    "document_id",
    "a_decision",
    "a_payload_json",
    "b_decision",
    "b_payload_json",
    "c_decision",
    "c_payload_json",
    "review_status",
    "annotator_id",
    "notes",
)
CANONICAL_ADJUDICATION_FIELDS = (
    "adjudication_id",
    "target_type",
    "event_id",
    "record_ids_json",
    "reason",
    "c_decision",
    "review_status",
    "annotator_id",
    "notes",
)


class ResolvedAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_key: str = Field(..., min_length=1)
    item_type: ItemType
    record_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    payload: dict | None
    resolution: Literal["agreement", "adjudicated"]


def initialize_gold_workspace(
    workspace: str | Path,
    *,
    effects: Iterable[ViewpointEffect] = (),
    claims: Iterable[AttributionClaim] = (),
    evidence_links: Iterable[EvidenceLink] = (),
) -> dict[str, object]:
    """Create identical pending candidate sheets for A and B.

    Candidate payloads are never Gold by themselves.  Every non-empty row must
    receive an explicit completed human decision before disagreement building.
    """
    root = Path(workspace)
    managed_files = _managed_files(root)
    existing = [str(path) for path in managed_files if path.exists()]
    if existing:
        raise FileExistsError(
            "Gold workspace already contains managed files: " + ", ".join(existing)
        )

    candidates = [
        *_candidate_rows("effect", list(effects)),
        *_candidate_rows("claim", list(claims)),
        *_candidate_rows("evidence", list(evidence_links)),
    ]
    for annotator in ("A", "B"):
        rows = [dict(row, annotator_id=annotator) for row in candidates]
        _write_csv(
            root / f"annotator_{annotator}" / "document_annotations.csv",
            ANNOTATION_FIELDS,
            rows,
        )
    _write_csv(
        root / "annotator_C" / "document_disagreements.csv",
        C_DISAGREEMENT_FIELDS,
        [],
    )
    write_jsonl(root / "process" / "agreements.jsonl", [])
    write_jsonl(root / "annotator_C" / "canonical_adjudication_queue.jsonl", [])
    _write_csv(
        root / "annotator_C" / "canonical_adjudication.csv",
        CANONICAL_ADJUDICATION_FIELDS,
        [],
    )
    manifest = {
        "workflow_version": "ea-gold-workflow-v1",
        "candidate_count": len(candidates),
        "llm_preannotation_policy": "candidate_only_requires_explicit_human_completion",
        "annotator_scope": "document_level_effect_claim_evidence",
        "canonical_policy": "automatic_then_C_only_for_needs_adjudication",
    }
    (root / "workflow_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "gold_workspace_initialized", **manifest}


def build_disagreement_queue(workspace: str | Path) -> dict[str, object]:
    """Resolve exact A/B agreements and send only disagreements to C."""
    root = Path(workspace)
    a_rows = _resolved_annotator_rows(
        root / "annotator_A" / "document_annotations.csv", "A"
    )
    b_rows = _resolved_annotator_rows(
        root / "annotator_B" / "document_annotations.csv", "B"
    )
    c_path = root / "annotator_C" / "document_disagreements.csv"
    existing_c = {
        row["annotation_key"]: row
        for row in _read_csv(c_path)
        if row.get("annotation_key")
    }
    agreements: list[ResolvedAnnotation] = []
    disagreements: list[dict[str, str]] = []
    for key in sorted(set(a_rows) | set(b_rows)):
        left = a_rows.get(key)
        right = b_rows.get(key)
        if left and right and _json_equal(left.payload, right.payload):
            agreements.append(
                ResolvedAnnotation(
                    annotation_key=key,
                    item_type=left.item_type,
                    record_id=left.record_id,
                    document_id=left.document_id,
                    payload=left.payload,
                    resolution="agreement",
                )
            )
            continue
        reference = left or right
        if reference is None:  # pragma: no cover - set union guarantees a row
            continue
        disagreement = {
            "annotation_key": key,
            "item_type": reference.item_type,
            "record_id": reference.record_id,
            "document_id": reference.document_id,
            "a_decision": _decision_label(left),
            "a_payload_json": _payload_json(left),
            "b_decision": _decision_label(right),
            "b_payload_json": _payload_json(right),
            "c_decision": "",
            "c_payload_json": "",
            "review_status": "pending",
            "annotator_id": "C",
            "notes": "",
        }
        previous = existing_c.get(key)
        if previous and all(
            previous.get(field, "") == disagreement[field]
            for field in ("a_payload_json", "b_payload_json")
        ):
            for field in ("c_decision", "c_payload_json", "review_status", "notes"):
                disagreement[field] = previous.get(field, "")
        disagreements.append(disagreement)
    write_jsonl(root / "process" / "agreements.jsonl", agreements)
    _write_csv(
        c_path,
        C_DISAGREEMENT_FIELDS,
        disagreements,
    )
    return {
        "status": "document_disagreement_queue_ready",
        "agreements": len(agreements),
        "needs_adjudication": len(disagreements),
    }


def export_gold_dataset(
    workspace: str | Path,
    *,
    sources: list[SourceRecord],
    documents: list[DocumentRecord],
) -> dict[str, object]:
    """Validate resolved rows, auto-group Canonical records, and export Gold."""
    root = Path(workspace)
    resolved = _resolved_document_annotations(root)
    effects: list[ViewpointEffect] = []
    claims: list[AttributionClaim] = []
    links: list[EvidenceLink] = []
    for row in resolved:
        if row.payload is None:
            continue
        _reject_human_canonical_fields(row.payload, row.annotation_key)
        if row.item_type == "effect":
            effects.append(ViewpointEffect.model_validate(row.payload))
        elif row.item_type == "claim":
            claims.append(AttributionClaim.model_validate(row.payload))
        else:
            links.append(EvidenceLink.model_validate(row.payload))

    effect_result = aggregate_effects(effects)
    final_effects, unresolved_effects = _apply_canonical_adjudication(
        root,
        list(effect_result.effects),
        list(effect_result.adjudication_queue),
        target_type="effect",
        id_field="effect_id",
        canonical_field="canonical_effect_id",
    )
    if unresolved_effects:
        write_jsonl(
            root / "annotator_C" / "canonical_adjudication_queue.jsonl",
            unresolved_effects,
        )
        return {
            "status": "needs_canonical_adjudication",
            "needs_adjudication": len(unresolved_effects),
            "gold_exported": False,
        }

    claim_result = aggregate_claims(claims, final_effects)
    final_claims, unresolved_claims = _apply_canonical_adjudication(
        root,
        list(claim_result.claims),
        list(claim_result.adjudication_queue),
        target_type="claim",
        id_field="claim_id",
        canonical_field="canonical_claim_group_id",
    )
    write_jsonl(
        root / "annotator_C" / "canonical_adjudication_queue.jsonl",
        unresolved_claims,
    )
    if unresolved_claims:
        return {
            "status": "needs_canonical_adjudication",
            "needs_adjudication": len(unresolved_claims),
            "gold_exported": False,
        }
    groups = _rebuild_claim_groups(final_claims, final_effects)
    assert_valid_cross_file_references(
        sources=sources,
        documents=documents,
        effects=final_effects,
        claims=final_claims,
        evidence_links=links,
        claim_groups=groups,
    )
    gold_dir = root / "gold"
    write_jsonl(gold_dir / "sources.jsonl", sources)
    write_jsonl(gold_dir / "documents.jsonl", documents)
    write_jsonl(gold_dir / "viewpoint_effects.jsonl", final_effects)
    write_jsonl(gold_dir / "attribution_claims.jsonl", final_claims)
    write_jsonl(gold_dir / "evidence_links.jsonl", links)
    write_jsonl(gold_dir / "canonical_claim_groups.jsonl", groups)
    return {
        "status": "gold_export_complete",
        "effects": len(final_effects),
        "claims": len(final_claims),
        "evidence_links": len(links),
        "canonical_claim_groups": len(groups),
        "needs_adjudication": 0,
        "gold_exported": True,
    }


def _candidate_rows(item_type: ItemType, rows: list[BaseModel]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        payload = row.model_dump(exclude_none=True)
        payload.pop("canonical_effect_id", None)
        payload.pop("canonical_claim_group_id", None)
        record_id = _record_id(item_type, payload)
        output.append(
            {
                "annotation_key": f"{item_type}:{record_id}",
                "item_type": item_type,
                "record_id": record_id,
                "document_id": str(payload["document_id"]),
                "candidate_origin": "llm_or_pipeline_candidate",
                "candidate_payload_json": json.dumps(
                    payload, ensure_ascii=False, sort_keys=True
                ),
                "human_decision": "",
                "human_payload_json": "",
                "review_status": "pending",
                "notes": "",
            }
        )
    return output


def _resolved_annotator_rows(
    path: Path, annotator: str
) -> dict[str, ResolvedAnnotation]:
    rows = _read_csv(path)
    output: dict[str, ResolvedAnnotation] = {}
    for line_number, row in enumerate(rows, start=2):
        if row.get("review_status") != "completed":
            raise ValueError(
                f"{path}:{line_number} is not completed; candidates are not Gold"
            )
        if row.get("annotator_id") != annotator:
            raise ValueError(f"{path}:{line_number} has wrong annotator_id")
        decision = row.get("human_decision", "")
        if decision not in {"accept", "revise", "reject", "add"}:
            raise ValueError(f"{path}:{line_number} has invalid human_decision")
        candidate = _parse_json(
            row.get("candidate_payload_json", ""), path, line_number
        )
        human = _parse_json(row.get("human_payload_json", ""), path, line_number)
        if decision == "accept":
            if candidate is None:
                raise ValueError(f"{path}:{line_number} accept requires a candidate")
            payload = candidate
        elif decision in {"revise", "add"}:
            if human is None:
                raise ValueError(
                    f"{path}:{line_number} {decision} requires human payload"
                )
            payload = human
        else:
            payload = None
        if payload is not None:
            _validate_annotation_metadata(row, payload, path, line_number)
        key = row.get("annotation_key", "")
        if not key or key in output:
            raise ValueError(
                f"{path}:{line_number} has missing or duplicate annotation_key"
            )
        output[key] = ResolvedAnnotation(
            annotation_key=key,
            item_type=row["item_type"],
            record_id=row["record_id"],
            document_id=row["document_id"],
            payload=payload,
            resolution="agreement",
        )
    return output


def _resolved_document_annotations(root: Path) -> list[ResolvedAnnotation]:
    agreements = [
        ResolvedAnnotation.model_validate(row)
        for row in _read_jsonl(root / "process" / "agreements.jsonl")
    ]
    adjudicated: list[ResolvedAnnotation] = []
    for line_number, row in enumerate(
        _read_csv(root / "annotator_C" / "document_disagreements.csv"), start=2
    ):
        if row.get("review_status") != "completed":
            raise ValueError(
                f"document disagreement {row.get('annotation_key')} is not completed"
            )
        if row.get("annotator_id") != "C":
            raise ValueError(f"C disagreement row {line_number} has wrong annotator_id")
        decision = row.get("c_decision", "")
        if decision == "choose_a":
            payload = _parse_json(row.get("a_payload_json", ""), root, line_number)
        elif decision == "choose_b":
            payload = _parse_json(row.get("b_payload_json", ""), root, line_number)
        elif decision == "custom":
            payload = _parse_json(row.get("c_payload_json", ""), root, line_number)
            if payload is None:
                raise ValueError("custom C decision requires c_payload_json")
        elif decision == "reject":
            payload = None
        else:
            raise ValueError(f"invalid C decision at row {line_number}")
        if payload is not None:
            _validate_annotation_metadata(row, payload, root, line_number)
        adjudicated.append(
            ResolvedAnnotation(
                annotation_key=row["annotation_key"],
                item_type=row["item_type"],
                record_id=row["record_id"],
                document_id=row["document_id"],
                payload=payload,
                resolution="adjudicated",
            )
        )
    resolved = [*agreements, *adjudicated]
    keys = [row.annotation_key for row in resolved]
    if len(keys) != len(set(keys)):
        raise ValueError("resolved Gold rows contain duplicate annotation_key")
    return resolved


def _reject_human_canonical_fields(payload: dict, annotation_key: str) -> None:
    forbidden = {"canonical_effect_id", "canonical_claim_group_id"} & payload.keys()
    if forbidden:
        raise ValueError(
            f"{annotation_key} contains program-owned Canonical fields: {sorted(forbidden)}"
        )


def _record_id(item_type: ItemType, payload: dict) -> str:
    field = {
        "effect": "effect_id",
        "claim": "claim_id",
        "evidence": "evidence_link_id",
    }[item_type]
    return str(payload[field])


def _managed_files(root: Path) -> list[Path]:
    return [
        root / "annotator_A" / "document_annotations.csv",
        root / "annotator_B" / "document_annotations.csv",
        root / "annotator_C" / "document_disagreements.csv",
        root / "annotator_C" / "canonical_adjudication.csv",
        root / "process" / "agreements.jsonl",
        root / "workflow_manifest.json",
    ]


def _decision_label(row: ResolvedAnnotation | None) -> str:
    if row is None:
        return "missing"
    return "reject" if row.payload is None else "accept_or_revise"


def _payload_json(row: ResolvedAnnotation | None) -> str:
    if row is None or row.payload is None:
        return ""
    return json.dumps(row.payload, ensure_ascii=False, sort_keys=True)


def _json_equal(left: dict | None, right: dict | None) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(
        right, ensure_ascii=False, sort_keys=True
    )


def _parse_json(value: str, path: object, line_number: int) -> dict | None:
    if not str(value or "").strip():
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}:{line_number} contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{path}:{line_number} payload must be a JSON object")
    return payload


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"required Gold workflow file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"required Gold workflow file not found: {path}")
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"{path}:{line_number} must be a JSON object")
        rows.append(payload)
    return rows


def _apply_canonical_adjudication(
    root: Path,
    records: list[BaseModel],
    queue: list[CanonicalAdjudicationRecord],
    *,
    target_type: str,
    id_field: str,
    canonical_field: str,
) -> tuple[list, list[CanonicalAdjudicationRecord]]:
    """Apply C's equivalence decision; program still generates Canonical IDs."""
    path = root / "annotator_C" / "canonical_adjudication.csv"
    existing = {
        row["adjudication_id"]: row
        for row in _read_csv(path)
        if row.get("adjudication_id")
    }
    sheet_rows = []
    decisions: dict[str, str] = {}
    unresolved = []
    for item in queue:
        old = existing.get(item.adjudication_id, {})
        decision = old.get("c_decision", "")
        completed = old.get("review_status") == "completed"
        if completed and decision not in {"merge", "keep_separate"}:
            raise ValueError(
                f"canonical adjudication {item.adjudication_id} has invalid C decision"
            )
        if completed:
            decisions[item.adjudication_id] = decision
        else:
            unresolved.append(item)
        sheet_rows.append(
            {
                "adjudication_id": item.adjudication_id,
                "target_type": item.target_type,
                "event_id": item.event_id,
                "record_ids_json": json.dumps(item.record_ids, ensure_ascii=False),
                "reason": item.reason,
                "c_decision": decision if completed else "",
                "review_status": "completed" if completed else "pending",
                "annotator_id": "C",
                "notes": old.get("notes", ""),
            }
        )
    other_rows = [
        row for row in existing.values() if row.get("target_type") != target_type
    ]
    _write_csv(
        path,
        CANONICAL_ADJUDICATION_FIELDS,
        [*other_rows, *sheet_rows],
    )
    if unresolved:
        return records, unresolved

    parent = {
        str(getattr(row, id_field)): str(getattr(row, id_field)) for row in records
    }

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for item in queue:
        if decisions[item.adjudication_id] == "merge":
            first, *rest = item.record_ids
            for record_id in rest:
                union(first, record_id)

    components: dict[str, list[str]] = {}
    for record_id in parent:
        components.setdefault(find(record_id), []).append(record_id)
    canonical_by_id: dict[str, str] = {}
    record_by_id = {str(getattr(row, id_field)): row for row in records}
    for member_ids in components.values():
        if len(member_ids) < 2:
            continue
        event_ids = {record_by_id[record_id].event_id for record_id in member_ids}
        if len(event_ids) != 1:
            raise ValueError("Canonical adjudication cannot cross events")
        generated = _adjudicated_canonical_id(
            canonical_field, next(iter(event_ids)), member_ids
        )
        canonical_by_id.update({record_id: generated for record_id in member_ids})
    return [
        row.model_copy(
            update={
                canonical_field: canonical_by_id.get(
                    str(getattr(row, id_field)), getattr(row, canonical_field)
                )
            }
        )
        for row in records
    ], []


def _adjudicated_canonical_id(
    canonical_field: str, event_id: str, record_ids: list[str]
) -> str:
    prefix = "ce" if canonical_field == "canonical_effect_id" else "ccg"
    encoded = event_id + "\n" + "\n".join(sorted(record_ids))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _validate_annotation_metadata(
    row: dict[str, str], payload: dict, path: Path, line_number: int
) -> None:
    item_type = row.get("item_type", "")
    if item_type not in {"effect", "claim", "evidence"}:
        raise ValueError(f"{path}:{line_number} has invalid item_type")
    payload_id = _record_id(item_type, payload)
    if payload_id != row.get("record_id"):
        raise ValueError(f"{path}:{line_number} payload record ID does not match row")
    if str(payload.get("document_id", "")) != row.get("document_id"):
        raise ValueError(f"{path}:{line_number} payload document_id does not match row")


def _rebuild_claim_groups(
    claims: list[AttributionClaim], effects: list[ViewpointEffect]
) -> list[CanonicalClaimGroup]:
    effect_by_id = {row.effect_id: row for row in effects}
    grouped: dict[str, list[AttributionClaim]] = {}
    for claim in claims:
        if not claim.canonical_claim_group_id:
            raise ValueError(f"Claim {claim.claim_id} lacks program Canonical ID")
        grouped.setdefault(claim.canonical_claim_group_id, []).append(claim)
    output = []
    for group_id, rows in sorted(grouped.items()):
        first = min(rows, key=lambda row: row.claim_id)
        canonical_effect_id = effect_by_id[first.effect_id].canonical_effect_id
        if not canonical_effect_id:
            raise ValueError(f"Effect {first.effect_id} lacks program Canonical ID")
        output.append(
            CanonicalClaimGroup(
                canonical_claim_group_id=group_id,
                event_id=first.event_id,
                canonical_effect_id=canonical_effect_id,
                relation_type=first.relation_type,
                normalized_explanation=min(row.normalized_explanation for row in rows),
                attribution_holder_category=first.attribution_holder_category,
                polarity=first.polarity,
                claim_ids=sorted(row.claim_id for row in rows),
            )
        )
    return output
