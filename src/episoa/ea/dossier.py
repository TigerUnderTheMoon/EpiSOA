"""Deterministic Event Dossier materialization with complete provenance."""

from __future__ import annotations

import hashlib
import json

from episoa.ea.schema import (
    AttributionClaim,
    CanonicalClaimGroup,
    CanonicalEffect,
    ClaimPairRelationRecord,
    DocumentRecord,
    DossierEdge,
    DossierProvenanceRecord,
    EventDossierRecord,
    EvidenceLink,
    SourceRecord,
    ViewpointEffect,
)


def materialize_event_dossiers(
    *,
    sources: list[SourceRecord],
    documents: list[DocumentRecord],
    effects: list[ViewpointEffect],
    claims: list[AttributionClaim],
    evidence_links: list[EvidenceLink],
    canonical_effects: list[CanonicalEffect],
    canonical_claim_groups: list[CanonicalClaimGroup],
    claim_pair_relations: list[ClaimPairRelationRecord],
) -> list[EventDossierRecord]:
    source_ids = _unique_ids(sources, "source_id")
    document_by_id = _unique_index(documents, "document_id")
    effect_by_id = _unique_index(effects, "effect_id")
    claim_by_id = _unique_index(claims, "claim_id")
    link_by_target: dict[tuple[str, str], list[EvidenceLink]] = {}
    for link in evidence_links:
        link_by_target.setdefault((link.target_type, link.target_id), []).append(link)
    for document in documents:
        if document.reporting_source_id not in source_ids:
            raise ValueError(f"{document.document_id}: missing ReportingSource")
        if document.primary_source_id not in source_ids:
            raise ValueError(f"{document.document_id}: missing PrimarySource")

    events = sorted(
        {row.event_id for row in canonical_effects}
        | {row.event_id for row in canonical_claim_groups}
    )
    output = []
    for event_id in events:
        event_effects = [row for row in canonical_effects if row.event_id == event_id]
        event_claim_groups = [
            row for row in canonical_claim_groups if row.event_id == event_id
        ]
        event_relations = [
            row for row in claim_pair_relations if row.event_id == event_id
        ]
        edges: set[tuple[str, str, str]] = set()
        provenance = []
        for canonical_effect in event_effects:
            edges.add(("contains", event_id, canonical_effect.canonical_effect_id))
            for effect_id in canonical_effect.member_effect_ids:
                effect = effect_by_id.get(effect_id)
                if effect is None or effect.event_id != event_id:
                    raise ValueError(
                        f"{canonical_effect.canonical_effect_id}: invalid Effect member"
                    )
                effect_links = link_by_target.get(("effect", effect_id), [])
                if not any(row.support_label == "supports" for row in effect_links):
                    raise ValueError(f"{effect_id}: missing supports Evidence Link")
                edges.add(("canonicalized_as", effect_id, canonical_effect.canonical_effect_id))
                edges.add(("reported_in", effect_id, effect.document_id))
                edges.add(("reported_by", effect.document_id, effect.reporting_source_id))
                edges.add(("derived_from", effect.document_id, effect.primary_source_id))
                for link in effect_links:
                    edges.add(("supported_by", effect_id, link.evidence_link_id))

        for group in event_claim_groups:
            edges.add(("belongs_to", group.canonical_claim_group_id, group.canonical_effect_id))
            for claim_id in group.claim_ids:
                claim = claim_by_id.get(claim_id)
                if claim is None or claim.event_id != event_id:
                    raise ValueError(
                        f"{group.canonical_claim_group_id}: invalid Claim member"
                    )
                document = document_by_id.get(claim.document_id)
                if document is None:
                    raise ValueError(f"{claim_id}: missing Document")
                claim_links = [
                    row
                    for row in link_by_target.get(("claim", claim_id), [])
                    if row.support_label == "supports"
                ]
                if not claim_links:
                    raise ValueError(f"{claim_id}: missing supports Evidence Link")
                edges.add(("belongs_to", claim_id, group.canonical_claim_group_id))
                edges.add(("claim_about_effect", claim_id, claim.effect_id))
                edges.add(("reported_in", claim_id, document.document_id))
                edges.add(("reported_by", document.document_id, document.reporting_source_id))
                edges.add(("derived_from", document.document_id, document.primary_source_id))
                for link in claim_links:
                    if link.document_id != claim.document_id:
                        raise ValueError(f"{link.evidence_link_id}: Claim provenance break")
                    edges.add(("supported_by", claim_id, link.evidence_link_id))
                provenance.append(
                    DossierProvenanceRecord(
                        canonical_claim_group_id=group.canonical_claim_group_id,
                        claim_id=claim_id,
                        document_id=claim.document_id,
                        reporting_source_id=claim.reporting_source_id,
                        primary_source_id=claim.primary_source_id,
                        evidence_link_ids=sorted(
                            row.evidence_link_id for row in claim_links
                        ),
                    )
                )
        for relation in event_relations:
            edges.add(("claim_pair_relation", relation.left_claim_id, relation.claim_pair_id))
            edges.add(("claim_pair_relation", relation.claim_pair_id, relation.right_claim_id))

        payload = {
            "event_id": event_id,
            "canonical_effect_ids": sorted(
                row.canonical_effect_id for row in event_effects
            ),
            "canonical_claim_group_ids": sorted(
                row.canonical_claim_group_id for row in event_claim_groups
            ),
            "claim_pair_relation_ids": sorted(
                row.claim_pair_id for row in event_relations
            ),
            "provenance": [
                row.model_dump()
                for row in sorted(
                    provenance, key=lambda row: (row.canonical_claim_group_id, row.claim_id)
                )
            ],
            "edges": [
                DossierEdge(edge_type=edge_type, source_id=source, target_id=target).model_dump()
                for edge_type, source, target in sorted(edges)
            ],
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        output.append(
            EventDossierRecord(
                **payload,
                dossier_hash="sha256:"
                + hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            )
        )
    return output


def _unique_ids(rows, field):
    values = [getattr(row, field) for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {field}")
    return set(values)


def _unique_index(rows, field):
    _unique_ids(rows, field)
    return {getattr(row, field): row for row in rows}
