"""Isolated EpiSOA-EA preparation, source-record, Fusion, and Dossier stages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from episoa.data.loader import read_typed_jsonl, write_jsonl
from episoa.ea.canonical import aggregate_effects, c_adjudication_rows
from episoa.ea.config import EAConfig
from episoa.ea.dossier import materialize_event_dossiers
from episoa.ea.extraction import EffectExtractionClient, extract_effect_candidates
from episoa.ea.fusion import FusionMethod, run_fusion
from episoa.ea.m3 import M3Clients, run_m3_core
from episoa.ea.preparation import prepare_documents, validate_document_registry
from episoa.ea.promotion import promote_effect_candidates
from episoa.ea.schema import (
    AttributionClaim,
    CanonicalClaimGroup,
    CanonicalEffect,
    ClaimPairRelationRecord,
    DocumentRecord,
    EffectCandidateRecord,
    EvidenceLink,
    RawDocumentInput,
    SemanticPairJudgmentRecord,
    SourceRecord,
    VerificationDiagnosticRecord,
    ViewpointEffect,
)
from episoa.ea.validation import assert_valid_cross_file_references


def prepare_m2_documents(config: EAConfig) -> dict[str, object]:
    raw_rows = read_typed_jsonl(config.data["raw_posts_path"], RawDocumentInput)
    prepared = prepare_documents(raw_rows)
    validate_document_registry(list(prepared.sources), list(prepared.documents))
    write_jsonl(config.data["sources_path"], prepared.sources)
    write_jsonl(config.data["documents_path"], prepared.documents)

    summary = {
        "status": "m2_documents_prepared",
        "run_id": config.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_sources": len(prepared.sources),
        "num_documents": len(prepared.documents),
        "ready_for_effect_extraction": True,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
        "next_stage": "M2_document_local_effect_extraction",
    }
    _write_summary(config, "m2_prepare_summary.json", summary)
    return summary


def run_m2_effect_extraction(
    config: EAConfig, llm_client: EffectExtractionClient
) -> dict[str, object]:
    sources = read_typed_jsonl(config.data["sources_path"], SourceRecord)
    documents = read_typed_jsonl(config.data["documents_path"], DocumentRecord)
    validate_document_registry(sources, documents)

    result = extract_effect_candidates(
        documents,
        llm_client,
        chunk_size_chars=int(config.runtime.get("chunk_size_chars", 6000)),
        chunk_overlap_chars=int(config.runtime.get("chunk_overlap_chars", 300)),
        schema_retries=int(config.runtime.get("schema_retries", 1)),
    )
    write_jsonl(config.data["effect_candidates_path"], result.candidates)
    write_jsonl(config.data["evidence_links_path"], result.evidence_links)
    write_jsonl(config.data["extraction_attempts_path"], result.attempts)

    run_dir = Path(config.output["runs_dir"]) / config.run_id
    write_jsonl(run_dir / "effect_candidates.jsonl", result.candidates)
    write_jsonl(run_dir / "evidence_links.jsonl", result.evidence_links)
    write_jsonl(run_dir / "extraction_attempts.jsonl", result.attempts)
    summary = {
        "status": "m2_effect_extraction_complete",
        "run_id": config.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_documents": len(documents),
        "num_effect_candidates": len(result.candidates),
        "num_evidence_links": len(result.evidence_links),
        "num_llm_attempts": len(result.attempts),
        "num_invalid_attempts": sum(not row.valid for row in result.attempts),
        "formal_effects_created": 0,
        "canonical_records_created": 0,
        "ready_for_m3": True,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
        "next_stage": "M3_explanation_relation_verification_claim_promotion",
    }
    _write_summary(config, "m2_extraction_summary.json", summary)
    return summary


def run_m3_pipeline(config: EAConfig, clients: M3Clients) -> dict[str, object]:
    """Run M3 from synthetic or future M2 artifacts, without M4 work."""
    sources = read_typed_jsonl(config.data["sources_path"], SourceRecord)
    documents = read_typed_jsonl(config.data["documents_path"], DocumentRecord)
    effect_candidates = read_typed_jsonl(
        config.data["effect_candidates_path"], EffectCandidateRecord
    )
    process_links = read_typed_jsonl(config.data["evidence_links_path"], EvidenceLink)
    effect_links = [row for row in process_links if row.target_type == "effect"]
    validate_document_registry(sources, documents)
    result = run_m3_core(
        documents=documents,
        effect_candidates=effect_candidates,
        effect_evidence_links=effect_links,
        clients=clients,
        schema_retries=int(config.runtime.get("schema_retries", 1)),
    )

    write_jsonl(
        config.data["explanation_candidates_path"], result.explanation_candidates
    )
    write_jsonl(config.data["relation_judgments_path"], result.relation_judgments)
    write_jsonl(
        config.data["verification_diagnostics_path"],
        result.verification_diagnostics,
    )
    write_jsonl(config.data["evidence_links_path"], result.evidence_links)
    formal_effects = list(result.effect_promotion.formal_effects)
    write_jsonl(config.data["viewpoint_effects_path"], formal_effects)
    write_jsonl(config.data["attribution_claims_path"], result.claims)
    write_jsonl(config.data["m3_attempts_path"], result.attempts)

    formal_effect_ids = {row.effect_id for row in formal_effects}
    formal_claim_ids = {row.claim_id for row in result.claims}
    formal_links = [
        row
        for row in result.evidence_links
        if (row.target_type == "effect" and row.target_id in formal_effect_ids)
        or (row.target_type == "claim" and row.target_id in formal_claim_ids)
    ]
    assert_valid_cross_file_references(
        sources=sources,
        documents=documents,
        effects=formal_effects,
        claims=list(result.claims),
        evidence_links=formal_links,
        claim_groups=[],
        claim_pairs=[],
    )

    run_dir = Path(config.output["runs_dir"]) / config.run_id
    outputs = {
        "explanation_candidates.jsonl": result.explanation_candidates,
        "relation_judgments.jsonl": result.relation_judgments,
        "verification_diagnostics.jsonl": result.verification_diagnostics,
        "evidence_links.jsonl": result.evidence_links,
        "viewpoint_effects.jsonl": formal_effects,
        "attribution_claims.jsonl": result.claims,
        "m3_attempts.jsonl": result.attempts,
    }
    for filename, rows in outputs.items():
        write_jsonl(run_dir / filename, rows)

    summary = {
        "status": "m3_core_complete",
        "run_id": config.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_effect_candidates": len(effect_candidates),
        "num_formal_effects": len(formal_effects),
        "num_explanation_candidates": len(result.explanation_candidates),
        "num_relation_judgments": len(result.relation_judgments),
        "num_formal_claims": len(result.claims),
        "num_claim_failures": len(result.claim_failures),
        "num_canonical_claim_groups": 0,
        "num_needs_adjudication": 0,
        "claim_pairs_created": 0,
        "ready_for_fusion": True,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
        "next_stage": "Fusion_APCF_or_baseline",
    }
    _write_summary(config, "m3_summary.json", summary)
    return summary


def run_fusion_pipeline(
    config: EAConfig, *, method: FusionMethod = "apcf"
) -> dict[str, object]:
    """Run cross-document fusion from immutable M3 source-level records."""
    documents = read_typed_jsonl(config.data["documents_path"], DocumentRecord)
    effects = read_typed_jsonl(config.data["viewpoint_effects_path"], ViewpointEffect)
    claims = read_typed_jsonl(config.data["attribution_claims_path"], AttributionClaim)
    semantic_path = Path(config.data["semantic_pair_judgments_path"])
    semantic = (
        read_typed_jsonl(semantic_path, SemanticPairJudgmentRecord)
        if semantic_path.is_file()
        else []
    )
    if method in {"llm", "embedding", "apcf"} and not semantic:
        raise ValueError(
            f"{method} fusion requires the frozen shared semantic judgment resource"
        )
    result = run_fusion(
        effects=effects,
        claims=claims,
        documents=documents,
        method=method,
        semantic_judgments=semantic,
        embedding_threshold=float(
            config.evaluation.get("fusion_embedding_threshold", 0.8)
        ),
    )
    outputs = {
        config.data["canonical_effects_path"]: result.canonical_effects,
        config.data["canonical_claim_groups_path"]: result.canonical_claim_groups,
        config.data["claim_pair_relations_path"]: result.claim_pair_relations,
        config.data["fusion_pair_judgments_path"]: result.pair_judgments,
        config.data["fusion_cluster_diagnostics_path"]: result.cluster_diagnostics,
        config.data["canonical_adjudication_queue_path"]: result.adjudication_queue,
    }
    if method == "apcf":
        for path, rows in outputs.items():
            write_jsonl(path, rows)
    run_dir = Path(config.output["runs_dir"]) / config.run_id / "fusion" / method
    for path, rows in outputs.items():
        write_jsonl(run_dir / Path(path).name, rows)
    summary = {
        "status": "fusion_complete",
        "run_id": config.run_id,
        "fusion_method": method,
        "num_canonical_effects": len(result.canonical_effects),
        "num_canonical_claim_groups": len(result.canonical_claim_groups),
        "num_claim_pair_relations": len(result.claim_pair_relations),
        "num_needs_adjudication": len(result.adjudication_queue),
        "formal_outputs_materialized": method == "apcf",
        "judgment_resource_ids": sorted(
            {row.judgment_resource_id for row in result.pair_judgments}
        ),
        "ready_for_dossier": method == "apcf",
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
    }
    _write_summary(config, f"fusion_{method}_summary.json", summary)
    return summary


def run_dossier_pipeline(config: EAConfig) -> dict[str, object]:
    """Materialize dossiers only from completed formal fusion outputs."""
    sources = read_typed_jsonl(config.data["sources_path"], SourceRecord)
    documents = read_typed_jsonl(config.data["documents_path"], DocumentRecord)
    effects = read_typed_jsonl(config.data["viewpoint_effects_path"], ViewpointEffect)
    claims = read_typed_jsonl(config.data["attribution_claims_path"], AttributionClaim)
    links = read_typed_jsonl(config.data["evidence_links_path"], EvidenceLink)
    canonical_effects = read_typed_jsonl(
        config.data["canonical_effects_path"], CanonicalEffect
    )
    groups = read_typed_jsonl(
        config.data["canonical_claim_groups_path"], CanonicalClaimGroup
    )
    pairs = read_typed_jsonl(
        config.data["claim_pair_relations_path"], ClaimPairRelationRecord
    )
    dossiers = materialize_event_dossiers(
        sources=sources,
        documents=documents,
        effects=effects,
        claims=claims,
        evidence_links=links,
        canonical_effects=canonical_effects,
        canonical_claim_groups=groups,
        claim_pair_relations=pairs,
    )
    write_jsonl(config.data["event_dossiers_path"], dossiers)
    run_dir = Path(config.output["runs_dir"]) / config.run_id / "dossier"
    write_jsonl(run_dir / "event_dossiers.jsonl", dossiers)
    summary = {
        "status": "dossier_complete",
        "run_id": config.run_id,
        "num_event_dossiers": len(dossiers),
        "provenance_complete": True,
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
    }
    _write_summary(config, "dossier_summary.json", summary)
    return summary


def run_m1_effect_gate(config: EAConfig) -> dict[str, object]:
    """Run the implemented M1 Effect promotion and Canonical interface offline."""
    candidates = read_typed_jsonl(
        config.data["effect_candidates_path"], EffectCandidateRecord
    )
    evidence_links = read_typed_jsonl(config.data["evidence_links_path"], EvidenceLink)
    diagnostics = read_typed_jsonl(
        config.data["verification_diagnostics_path"],
        VerificationDiagnosticRecord,
    )
    promotion = promote_effect_candidates(candidates, evidence_links, diagnostics)
    canonical = aggregate_effects(list(promotion.formal_effects))

    run_dir = Path(config.output["runs_dir"]) / config.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(run_dir / "effect_candidates.jsonl", candidates)
    write_jsonl(run_dir / "evidence_links.jsonl", evidence_links)
    write_jsonl(run_dir / "verification_diagnostics.jsonl", promotion.diagnostics)
    write_jsonl(run_dir / "viewpoint_effects.jsonl", canonical.effects)
    write_jsonl(
        run_dir / "canonical_adjudication_queue.jsonl",
        c_adjudication_rows(list(canonical.adjudication_queue)),
    )

    summary = {
        "status": "m1_effect_gate_complete",
        "run_id": config.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "num_effect_candidates": len(candidates),
        "num_formal_effects": len(canonical.effects),
        "num_failed_candidates": len(promotion.failures),
        "num_needs_adjudication": len(canonical.adjudication_queue),
        "ready_for_pilot": False,
        "ready_for_formal_collection": False,
        "next_stage": "M2_document_level_extraction",
    }
    (run_dir / "m1_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _write_summary(config: EAConfig, filename: str, summary: dict[str, object]) -> None:
    run_dir = Path(config.output["runs_dir"]) / config.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / filename).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
