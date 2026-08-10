from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from episoa.ea.baselines import (
    ComparisonManifest,
    FairnessProtocol,
    LongContextFreezeManifest,
    build_comparison_manifest,
    preflight_long_context,
    run_long_context_adapter,
)
from episoa.ea.dossier import materialize_event_dossiers
from episoa.ea.fusion import (
    claim_candidate_pairs,
    make_pair_id,
    membership_id,
    run_fusion,
)
from episoa.ea.fusion_evaluation import (
    FusionComparisonManifest,
    FusionMethodRunSpec,
    canonicalization_metrics,
    conflict_preservation_rate,
)
from episoa.ea.fusion_gold import (
    BlockerFreezeManifest,
    FusionPairSheetRecord,
    blocking_recall,
)
from episoa.ea.schema import (
    AttributionClaim,
    DocumentRecord,
    EvidenceLink,
    SemanticPairJudgmentRecord,
    SourceRecord,
    ViewpointEffect,
    content_hash,
)


def _source(source_id: str) -> SourceRecord:
    return SourceRecord(source_id=source_id, source_name=source_id, source_type="news")


def _document(
    document_id: str,
    text: str,
    *,
    source_id: str,
    derivation_type: str = "original",
    primary_source_id: str | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        event_id="EV1",
        reporting_source_id=source_id,
        primary_source_id=primary_source_id or source_id,
        derivation_type=derivation_type,
        normalized_text=text,
        content_hash=content_hash(text),
    )


def _effect(
    effect_id: str,
    document: DocumentRecord,
    *,
    value: str = "oppose",
    target: str = "补偿方案",
    stage: str = "conflict",
    effect_type: str = "stance",
    holder_surface: str = "居民",
) -> ViewpointEffect:
    return ViewpointEffect(
        effect_id=effect_id,
        event_id=document.event_id,
        document_id=document.document_id,
        reporting_source_id=document.reporting_source_id,
        primary_source_id=document.primary_source_id,
        derivation_type=document.derivation_type,
        stakeholder_category="affected_public",
        holder_surface=holder_surface,
        holder_role="居民",
        effect_type=effect_type,
        effect_surface=f"{holder_surface}反对",
        effect_value=value,
        target=target,
        effect_stage=stage,
    )


def _claim(
    claim_id: str,
    effect: ViewpointEffect,
    *,
    holder: str,
    category: str,
    explanation: str = "补偿标准低",
) -> AttributionClaim:
    return AttributionClaim(
        claim_id=claim_id,
        effect_id=effect.effect_id,
        event_id=effect.event_id,
        document_id=effect.document_id,
        reporting_source_id=effect.reporting_source_id,
        primary_source_id=effect.primary_source_id,
        derivation_type=effect.derivation_type,
        explanation_surface=explanation,
        normalized_explanation=explanation,
        relation_type="stance_rationale",
        attribution_holder_category=category,
        attribution_holder_surface=holder,
        attribution_holder_role=holder,
        claim_stage=effect.effect_stage,
        explicitness="explicit",
        certainty="certain",
        polarity="affirmed",
    )


def _semantic(
    target_type: str,
    left_id: str,
    right_id: str,
    label: str,
    *,
    score: float = 1.0,
    temporal: str = "compatible",
) -> SemanticPairJudgmentRecord:
    left_id, right_id = sorted((left_id, right_id))
    return SemanticPairJudgmentRecord(
        pair_id=make_pair_id(target_type, left_id, right_id),
        target_type=target_type,
        event_id="EV1",
        left_id=left_id,
        right_id=right_id,
        semantic_label=label,
        semantic_score=score,
        temporal_compatibility=temporal,
        judgment_resource_id="shared-pairs-v1",
        model_version="mock-v1",
        prompt_version="pair-v1",
        decoding_version="temperature-0",
    )


def _evidence(target_type: str, target_id: str, document: DocumentRecord) -> EvidenceLink:
    return EvidenceLink(
        evidence_link_id=f"EL-{target_id}",
        target_type=target_type,
        target_id=target_id,
        document_id=document.document_id,
        evidence_id=f"EV-{target_id}",
        span_id=f"SP-{target_id}",
        char_start=0,
        char_end=len(document.normalized_text),
        span_text=document.normalized_text,
        support_field="explanation_surface" if target_type == "claim" else "holder_surface",
        support_label="supports",
    )


def test_holder_surfaces_have_frozen_grounding_contract() -> None:
    document = _document("D1", "居民反对补偿方案", source_id="S1")
    with pytest.raises(ValidationError):
        ViewpointEffect.model_validate(
            _effect("E1", document).model_dump(exclude={"holder_surface"})
        )
    claim = _claim("C1", _effect("E1", document), holder="居民", category="affected_public")
    assert claim.model_copy(update={"attribution_holder_surface": None}).attribution_holder_surface is None


def test_effect_fusion_uses_semantic_compatibility_and_stage_is_observation() -> None:
    d1 = _document("D1", "居民反对补偿方案", source_id="S1")
    d2 = _document("D2", "居民仍拒绝现行补偿安置方案", source_id="S2")
    e1 = _effect("E1", d1, stage="conflict")
    e2 = _effect("E2", d2, target="现行补偿安置方案", stage="response")
    result = run_fusion(
        effects=[e2, e1],
        claims=[],
        documents=[d2, d1],
        method="apcf",
        semantic_judgments=[_semantic("effect", "E1", "E2", "equivalent_effect")],
    )
    assert len(result.canonical_effects) == 1
    canonical = result.canonical_effects[0]
    assert canonical.observed_stages == ["conflict", "response"]
    assert canonical.canonical_effect_id == membership_id("ce", "EV1", ["E1", "E2"])
    assert e1.canonical_effect_id is None and e2.canonical_effect_id is None


def test_equivalent_explanation_with_different_holder_is_not_merged() -> None:
    d1 = _document("D1", "居民称补偿低", source_id="S1")
    d2 = _document("D2", "专家称补偿低", source_id="S2")
    e1, e2 = _effect("E1", d1), _effect("E2", d2)
    c1 = _claim("C1", e1, holder="居民", category="affected_public")
    c2 = _claim("C2", e2, holder="专家", category="expert")
    judgments = [
        _semantic("effect", "E1", "E2", "equivalent_effect"),
        _semantic("claim", "C1", "C2", "equivalent_explanation"),
    ]
    result = run_fusion(
        effects=[e1, e2],
        claims=[c1, c2],
        documents=[d1, d2],
        method="apcf",
        semantic_judgments=judgments,
    )
    claim_pair = next(row for row in result.pair_judgments if row.target_type == "claim")
    assert claim_pair.semantic_label == "equivalent_explanation"
    assert claim_pair.merge_decision == "cannot_link"
    assert claim_pair.reason_codes == ["attribution_holder_mismatch"]
    assert len(result.canonical_claim_groups) == 2
    assert result.claim_pair_relations[0].relation == "equivalent_explanation"


def test_claim_pair_universe_does_not_depend_on_predicted_effect_membership() -> None:
    d1 = _document("D1", "居民称补偿低", source_id="S1")
    d2 = _document("D2", "居民称安置慢", source_id="S2")
    e1 = _effect("E1", d1, target="补偿方案")
    e2 = _effect("E2", d2, target="安置进度")
    claims = [
        _claim("C1", e1, holder="居民", category="affected_public"),
        _claim("C2", e2, holder="居民", category="affected_public"),
    ]
    assert claim_candidate_pairs(claims, {"E1": "CE1", "E2": "CE1"}) == [
        ("C1", "C2")
    ]
    assert claim_candidate_pairs(claims, {"E1": "CE1", "E2": "CE2"}) == [
        ("C1", "C2")
    ]


def test_complete_link_blocks_transitive_merge_when_cross_pair_is_unresolved() -> None:
    docs = [_document(f"D{i}", f"居民观点{i}", source_id=f"S{i}") for i in range(1, 4)]
    effects = [_effect(f"E{i}", docs[i - 1], target=f"方案{i}") for i in range(1, 4)]
    result = run_fusion(
        effects=effects,
        claims=[],
        documents=docs,
        method="apcf",
        semantic_judgments=[
            _semantic("effect", "E1", "E2", "equivalent_effect"),
            _semantic("effect", "E2", "E3", "equivalent_effect"),
        ],
    )
    assert sorted(len(row.member_effect_ids) for row in result.canonical_effects) == [1, 2]
    assert any(
        row.decision == "needs_adjudication" for row in result.cluster_diagnostics
    )
    assert any(row.record_ids == ["E1", "E3"] for row in result.adjudication_queue)


def test_lineage_multiplicities_do_not_invent_partial_independence() -> None:
    d1 = _document("D1", "居民反对", source_id="S1", primary_source_id="S1")
    d2 = _document(
        "D2",
        "转载居民反对",
        source_id="S2",
        primary_source_id="S1",
        derivation_type="syndicated_copy",
    )
    e1, e2 = _effect("E1", d1), _effect("E2", d2)
    result = run_fusion(
        effects=[e1, e2],
        claims=[],
        documents=[d1, d2],
        method="exact",
    )
    canonical = result.canonical_effects[0]
    assert canonical.document_multiplicity == 2
    assert canonical.primary_source_multiplicity == 1
    assert canonical.dependent_reproduction_count == 1
    assert canonical.unknown_lineage_count == 0


def test_dossier_materialization_preserves_full_claim_provenance() -> None:
    d1 = _document("D1", "居民称补偿标准低", source_id="S1")
    e1 = _effect("E1", d1)
    c1 = _claim("C1", e1, holder="居民", category="affected_public")
    fusion = run_fusion(
        effects=[e1], claims=[c1], documents=[d1], method="exact"
    )
    dossiers = materialize_event_dossiers(
        sources=[_source("S1")],
        documents=[d1],
        effects=[e1],
        claims=[c1],
        evidence_links=[_evidence("effect", "E1", d1), _evidence("claim", "C1", d1)],
        canonical_effects=list(fusion.canonical_effects),
        canonical_claim_groups=list(fusion.canonical_claim_groups),
        claim_pair_relations=[],
    )
    assert len(dossiers) == 1
    assert dossiers[0].provenance[0].claim_id == "C1"
    assert dossiers[0].dossier_hash.startswith("sha256:")
    edge_keys = {
        (edge.edge_type, edge.source_id, edge.target_id)
        for edge in dossiers[0].edges
    }
    assert ("claim_about_effect", "C1", "E1") in edge_keys
    assert ("reported_in", "C1", "D1") in edge_keys
    assert ("reported_by", "D1", "S1") in edge_keys
    assert all("cause" not in edge.edge_type for edge in dossiers[0].edges)


def test_blocking_recall_and_freeze_are_preregistered() -> None:
    effect_pair = FusionPairSheetRecord(
        pair_id="PE",
        target_type="effect",
        event_id="EV1",
        left_id="E1",
        right_id="E2",
        semantic_label="equivalent_effect",
        annotator_id="Gold",
    )
    claim_pair = FusionPairSheetRecord(
        pair_id="PC",
        target_type="claim",
        event_id="EV1",
        left_id="C1",
        right_id="C2",
        semantic_label="equivalent_explanation",
        annotator_id="Gold",
    )
    metrics = blocking_recall([effect_pair, claim_pair], {"PE", "PC"})
    assert metrics["effect"]["recall"] == 1.0
    assert metrics["claim"]["recall"] == 1.0
    manifest = BlockerFreezeManifest(
        blocker_version="block-v1",
        pair_universe_hash="sha256:test",
        effect_blocking_recall=1.0,
        claim_blocking_recall=1.0,
        frozen_before_formal_inference=True,
    )
    assert manifest.threshold == 0.98
    with pytest.raises(ValidationError):
        BlockerFreezeManifest.model_validate(
            {**manifest.model_dump(), "formal_results_seen": True}
        )


def test_llm_pairwise_and_apcf_must_share_pair_judgment_resource() -> None:
    common = {
        "candidate_set_hash": "hash",
        "normalization_version": "norm",
        "gold_version": "gold",
        "judgment_resource_id": "shared",
        "model_version": "model",
        "prompt_version": "prompt",
        "decoding_version": "temperature-0",
        "temperature": 0.0,
        "token_budget": 8192,
        "failure_policy": "fail_closed",
    }
    manifest = FusionComparisonManifest(
        runs=[
            FusionMethodRunSpec(method_id=method, **common)
            for method in ("exact", "embedding", "llm_pairwise", "apcf")
        ]
    )
    broken = manifest.model_dump()
    broken["runs"][3]["prompt_version"] = "stronger-apcf-prompt"
    with pytest.raises(ValidationError, match="must share prompt_version"):
        FusionComparisonManifest.model_validate(broken)
    broken = manifest.model_dump()
    broken["runs"][3]["token_budget"] = 4096
    with pytest.raises(ValidationError, match="must share token_budget"):
        FusionComparisonManifest.model_validate(broken)


def test_main_comparison_uses_one_base_llm_and_applicability() -> None:
    protocol = FairnessProtocol(
        document_set_hash="docs", gold_version="gold", split_version="split"
    )
    manifest = build_comparison_manifest(
        protocol,
        model_name="same-model-v1",
        prompt_version="prompt",
        decoding_version="temperature-0",
        seed=0,
        output_root="out",
        token_budget=8192,
    )
    assert isinstance(manifest, ComparisonManifest)
    assert len(manifest.runs) == 5
    assert {row.token_budget for row in manifest.runs} == {8192}


def test_pre_pilot_registry_freezes_one_event_per_domain() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = yaml.safe_load(
        (root / "configs" / "ea_pilot_events.yaml").read_text(encoding="utf-8")
    )
    events = registry["events"]
    assert registry["selection_constraints"]["event_count"] == 6
    assert len(events) == 6
    assert {row["domain"] for row in events} == {
        "urban_renewal",
        "education",
        "healthcare",
        "public_safety",
        "urban_transport",
        "digital_governance",
    }
    assert registry["selection_constraints"]["pilot_excluded_from_formal_test"] is True
    assert registry["selection_constraints"]["target_documents_per_event"] == "6-8"


def test_pre_pilot_model_contract_disables_thinking_and_freezes_json_mode() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("ea_pilot.yaml", "ea_ablation.yaml"):
        config = yaml.safe_load(
            (root / "configs" / name).read_text(encoding="utf-8")
        )
        model = config["model"]
        assert model["llm_model"] == "deepseek-v4-flash"
        assert model["model_version"] == "DeepSeek-V4-Flash-2026-04-24"
        assert model["thinking_mode"] == "disabled"
        assert model["response_format_mode"] == "json_object"
        assert model["max_tokens"] == 8192


def test_long_context_preflight_freezes_before_results_and_never_truncates() -> None:
    freeze = preflight_long_context(
        {"EV1": "abc"},
        token_counter=len,
        model_name="model",
        model_version="v1",
        provider="mock",
        context_window_tokens=10,
        reserved_output_tokens=2,
    )

    class Client:
        def chat(self, **kwargs):
            return SimpleNamespace(content=json.dumps({"ok": True}))

    result = run_long_context_adapter(
        {"EV1": "abc"}, client=Client(), freeze=freeze, requires_evidence=True
    )
    assert result[0].status == "success"
    with pytest.raises(ValidationError, match="capacity is insufficient"):
        LongContextFreezeManifest(
            model_name="small",
            model_version="v1",
            provider="mock",
            context_window_tokens=4,
            reserved_output_tokens=2,
            event_input_tokens={"EV1": 3},
            frozen_before_formal_inference=True,
        )


def test_fusion_metrics_exclude_unresolved_and_conflict_gate_can_be_na() -> None:
    metrics = canonicalization_metrics(
        {"A": "G1", "B": "G1", "C": "G2"},
        {"A": "P1", "B": "P2", "C": "P2"},
        excluded_pairs={("A", "C")},
    )
    assert metrics["false_split_pairs"] == 1
    assert metrics["false_merge_pairs"] == 1
    assert metrics["excluded_pairs"] == 1
    assert conflict_preservation_rate([], {})["gate_status"] == "NA"
