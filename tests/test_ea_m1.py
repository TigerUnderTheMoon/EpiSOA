from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from episoa.cli import build_parser
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.ea.canonical import (
    aggregate_claims,
    aggregate_effects,
    annotator_document_rows,
    c_adjudication_rows,
)
from episoa.ea.config import (
    EA_ABLATION_SETTINGS,
    EA_FUSION_ABLATION_SETTINGS,
    EAConfig,
    load_ea_config,
)
from episoa.ea.matching import SemanticEquivalenceRules, match_explanation
from episoa.ea.pipeline import run_m1_effect_gate
from episoa.ea.promotion import promote_effect_candidates
from episoa.ea.relations import relation_evaluation_label
from episoa.ea.schema import (
    AttributionClaim,
    DocumentRecord,
    EffectCandidateRecord,
    EvidenceLink,
    RelationJudgmentRecord,
    SourceRecord,
    VerificationDiagnosticRecord,
    ViewpointEffect,
    content_hash,
)
from episoa.ea.validation import validate_cross_file_references

REQUIRED_FIELDS = (
    "holder_surface",
    "stakeholder_category",
    "effect_type",
    "effect_value",
    "target",
    "effect_stage",
)


def effect_candidate(
    effect_id: str = "EF001", *, target: str = "补偿方案"
) -> EffectCandidateRecord:
    return EffectCandidateRecord(
        effect_id=effect_id,
        event_id="E001",
        document_id="D001",
        reporting_source_id="SRC001",
        primary_source_id="SRC001",
        derivation_type="original",
        stakeholder_category="affected_public",
        holder_surface="业主",
        holder_role="业主",
        effect_type="stance",
        effect_surface="反对补偿方案",
        effect_value="oppose",
        target=target,
        effect_stage="conflict",
    )


def effect_links(effect_id: str = "EF001") -> list[EvidenceLink]:
    spans = {
        "holder_surface": (0, 2, "业主"),
        "stakeholder_category": (0, 2, "业主"),
        "effect_type": (2, 4, "反对"),
        "effect_value": (2, 4, "反对"),
        "target": (4, 8, "补偿方案"),
        "effect_stage": (0, 8, "业主反对补偿方案"),
    }
    return [
        EvidenceLink(
            evidence_link_id=f"EL-{effect_id}-{index}",
            target_type="effect",
            target_id=effect_id,
            document_id="D001",
            evidence_id="EV001",
            span_id=f"SP-{index}",
            char_start=start,
            char_end=end,
            span_text=text,
            support_field=field,
            support_label="supports",
        )
        for index, (field, (start, end, text)) in enumerate(spans.items(), start=1)
    ]


def verified_diagnostic(effect_id: str = "EF001") -> VerificationDiagnosticRecord:
    return VerificationDiagnosticRecord(
        verification_id=f"VER-{effect_id}",
        target_type="effect",
        target_id=effect_id,
        status="verified",
        field_statuses={field: "verified" for field in REQUIRED_FIELDS},
    )


def formal_effect(
    effect_id: str = "EF001", *, target: str = "补偿方案", document_id: str = "D001"
) -> ViewpointEffect:
    payload = effect_candidate(effect_id, target=target).model_dump()
    payload["document_id"] = document_id
    return ViewpointEffect(**payload)


def claim(claim_id: str, effect_id: str, explanation: str) -> AttributionClaim:
    return AttributionClaim(
        claim_id=claim_id,
        effect_id=effect_id,
        event_id="E001",
        document_id="D001",
        reporting_source_id="SRC001",
        primary_source_id="SRC001",
        derivation_type="original",
        explanation_surface=explanation,
        normalized_explanation=explanation,
        relation_type="stance_rationale",
        attribution_holder_category="affected_public",
        attribution_holder_surface="业主",
        attribution_holder_role="业主",
        claim_stage="conflict",
        explicitness="explicit",
        certainty="certain",
        polarity="affirmed",
    )


def test_frozen_effect_labels_reject_legacy_mixed_emotion() -> None:
    payload = effect_candidate().model_dump()
    payload.update(
        effect_type="emotion", effect_value="mixed", effect_surface="情绪复杂"
    )
    with pytest.raises(ValidationError):
        EffectCandidateRecord(**payload)


def test_formal_claim_rejects_relation_decision_field() -> None:
    payload = claim("CL001", "EF001", "补偿标准不足").model_dump()
    payload["relation_decision"] = "supported"
    with pytest.raises(ValidationError):
        AttributionClaim(**payload)


def test_relation_decision_and_evaluation_label_are_separate() -> None:
    assert relation_evaluation_label("stance", "supported") == "stance_rationale"
    assert relation_evaluation_label("emotion", "supported") == "emotion_trigger"
    assert relation_evaluation_label("action", "supported") == "action_motivation"
    assert relation_evaluation_label("stance", "no_relation") == "no_relation"
    with pytest.raises(ValidationError):
        RelationJudgmentRecord(
            relation_judgment_id="RJ001",
            explanation_candidate_id="EX001",
            effect_id="EF001",
            event_id="E001",
            document_id="D001",
            effect_type="stance",
            relation_decision="no_relation",
            relation_type="stance_rationale",
            attribution_holder_category="affected_public",
            claim_stage="conflict",
            explicitness="explicit",
            certainty="certain",
            polarity="affirmed",
        )


def test_effect_promotion_requires_verified_fields_and_support_links() -> None:
    candidate = effect_candidate()
    result = promote_effect_candidates(
        [candidate], effect_links(), [verified_diagnostic()]
    )
    assert [row.effect_id for row in result.formal_effects] == ["EF001"]
    assert not result.failures

    insufficient = promote_effect_candidates(
        [candidate],
        effect_links()[:-1],
        [verified_diagnostic()],
    )
    assert not insufficient.formal_effects
    assert insufficient.failures[0].effect_id == "EF001"
    assert insufficient.diagnostics[0].status == "insufficient"


def test_explanation_match_uses_span_overlap_or_shared_semantic_rules() -> None:
    rules = SemanticEquivalenceRules(
        version="v1",
        groups=[["补偿标准偏低", "补偿金额未达预期"]],
    )
    gold_link = EvidenceLink(
        evidence_link_id="EL-G",
        target_type="claim",
        target_id="CL-G",
        document_id="D001",
        evidence_id="EV001",
        span_id="SP-G",
        char_start=0,
        char_end=8,
        span_text="补偿标准低于预期",
        support_field="explanation_surface",
        support_label="supports",
    )
    pred_link = gold_link.model_copy(
        update={
            "evidence_link_id": "EL-P",
            "target_id": "CL-P",
            "span_id": "SP-P",
            "span_text": "补偿低于预期",
            "char_end": 6,
        }
    )
    span_result = match_explanation(
        gold_explanation="不同字符串A",
        prediction_explanation="不同字符串B",
        gold_links=[gold_link],
        prediction_links=[pred_link],
        rules=rules,
    )
    assert span_result.matched is True
    assert span_result.method == "span_overlap"

    rule_result = match_explanation(
        gold_explanation="补偿标准偏低",
        prediction_explanation="补偿金额未达预期",
        gold_links=[],
        prediction_links=[],
        rules=rules,
    )
    assert rule_result.matched is True
    assert rule_result.method == "semantic_rule"


def test_canonical_ids_are_program_owned_and_only_ambiguities_reach_c() -> None:
    effects = [
        formal_effect("EF001", target="补偿方案", document_id="D001"),
        formal_effect("EF002", target="补偿方案", document_id="D002"),
        formal_effect("EF003", target="补偿安置方案", document_id="D003"),
    ]
    effect_result = aggregate_effects(effects)
    by_id = {row.effect_id: row for row in effect_result.effects}
    assert by_id["EF001"].canonical_effect_id == by_id["EF002"].canonical_effect_id
    assert by_id["EF001"].canonical_effect_id != by_id["EF003"].canonical_effect_id
    assert effect_result.adjudication_queue
    assert all(
        row.status == "needs_adjudication" for row in effect_result.adjudication_queue
    )
    assert all(
        "canonical_effect_id" not in row
        for row in annotator_document_rows(list(effect_result.effects))
    )
    assert all(
        row["status"] == "needs_adjudication"
        for row in c_adjudication_rows(list(effect_result.adjudication_queue))
    )

    claims = [
        claim("CL001", "EF001", "补偿标准低于预期"),
        claim("CL002", "EF002", "补偿标准低于预期"),
        claim("CL003", "EF003", "补偿金额没有达到预期"),
    ]
    claim_result = aggregate_claims(claims, list(effect_result.effects))
    assert claim_result.groups
    assert all(
        "canonical_claim_group_id" not in row
        for row in annotator_document_rows(list(claim_result.claims))
    )


def test_canonical_aggregation_keeps_obviously_different_effects_separate() -> None:
    oppose = formal_effect("EF001")
    support_payload = formal_effect("EF002").model_dump()
    support_payload.update(effect_surface="支持补偿方案", effect_value="support")
    result = aggregate_effects([oppose, ViewpointEffect(**support_payload)])

    assert (
        result.effects[0].canonical_effect_id != result.effects[1].canonical_effect_id
    )
    assert result.adjudication_queue == ()


def test_ea_config_rejects_legacy_paths() -> None:
    with pytest.raises(ValidationError):
        EAConfig(
            run_id="bad",
            mode="ea_pilot",
            data={
                "raw_posts_path": "data/pubevent_soa_lite/raw.jsonl",
                "sources_path": "data/ea/sources.jsonl",
                "documents_path": "data/ea/documents.jsonl",
                "effect_candidates_path": "data/ea/effects.jsonl",
                "explanation_candidates_path": "data/ea/explanations.jsonl",
                "relation_judgments_path": "data/ea/relations.jsonl",
                "evidence_links_path": "data/ea/links.jsonl",
                "extraction_attempts_path": "data/ea/attempts.jsonl",
                "m3_attempts_path": "data/ea/m3_attempts.jsonl",
                "verification_diagnostics_path": "data/ea/diagnostics.jsonl",
                "viewpoint_effects_path": "data/ea/formal_effects.jsonl",
                "attribution_claims_path": "data/ea/claims.jsonl",
                "canonical_claim_groups_path": "data/ea/groups.jsonl",
                "canonical_adjudication_queue_path": "data/ea/adjudication.jsonl",
            },
            output={"runs_dir": "outputs/ea", "cache_dir": "outputs/ea/cache"},
        )


def test_ea_configs_and_cli_expose_only_the_frozen_m1_interfaces() -> None:
    pilot = load_ea_config("configs/ea_pilot.yaml")
    ablation = load_ea_config("configs/ea_ablation.yaml")
    assert pilot.mode == "ea_pilot"
    assert ablation.mode == "ea_ablation"
    assert tuple(ablation.ablation["settings"]) == (
        *EA_ABLATION_SETTINGS,
        *EA_FUSION_ABLATION_SETTINGS,
    )
    parser = build_parser()
    for command in ("ea-status", "prepare-ea", "run-ea", "run-ea-ablation"):
        assert parser.parse_args([command]).command == command
    assert parser.parse_args(["run-ea", "--stage", "m3"]).stage == "m3"


def test_cross_file_validation_checks_provenance_and_exact_span_round_trip() -> None:
    source = SourceRecord(
        source_id="SRC001", source_name="测试媒体", source_type="news"
    )
    document = DocumentRecord(
        document_id="D001",
        event_id="E001",
        reporting_source_id="SRC001",
        primary_source_id="SRC001",
        content_hash=content_hash("业主反对补偿方案"),
        derivation_type="original",
        normalized_text="业主反对补偿方案",
    )
    effect = formal_effect().model_copy(update={"canonical_effect_id": "CEF001"})
    assert (
        validate_cross_file_references(
            sources=[source],
            documents=[document],
            effects=[effect],
            claims=[],
            evidence_links=effect_links(),
        )
        == []
    )

    bad_link = effect_links()[0].model_copy(update={"span_text": "居民"})
    issues = validate_cross_file_references(
        sources=[source],
        documents=[document],
        effects=[effect],
        claims=[],
        evidence_links=[bad_link, *effect_links()[1:]],
    )
    assert any(issue.code == "span_text_mismatch" for issue in issues)


def test_m1_gate_materializes_only_promoted_effects(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    data_dir.mkdir()
    write_jsonl(data_dir / "effect_candidates.jsonl", [effect_candidate()])
    write_jsonl(data_dir / "evidence_links.jsonl", effect_links())
    write_jsonl(data_dir / "verification_diagnostics.jsonl", [verified_diagnostic()])
    config = {
        "run_id": "m1-test",
        "mode": "ea_pilot",
        "data": {
            "raw_posts_path": str(data_dir / "raw.jsonl"),
            "sources_path": str(data_dir / "sources.jsonl"),
            "documents_path": str(data_dir / "documents.jsonl"),
            "effect_candidates_path": str(data_dir / "effect_candidates.jsonl"),
            "explanation_candidates_path": str(
                data_dir / "explanation_candidates.jsonl"
            ),
            "relation_judgments_path": str(data_dir / "relation_judgments.jsonl"),
            "evidence_links_path": str(data_dir / "evidence_links.jsonl"),
            "extraction_attempts_path": str(data_dir / "extraction_attempts.jsonl"),
            "m3_attempts_path": str(data_dir / "m3_attempts.jsonl"),
            "verification_diagnostics_path": str(
                data_dir / "verification_diagnostics.jsonl"
            ),
            "viewpoint_effects_path": str(data_dir / "viewpoint_effects.jsonl"),
            "attribution_claims_path": str(data_dir / "attribution_claims.jsonl"),
            "canonical_claim_groups_path": str(
                data_dir / "canonical_claim_groups.jsonl"
            ),
            "canonical_adjudication_queue_path": str(
                data_dir / "canonical_adjudication_queue.jsonl"
            ),
        },
        "output": {
            "runs_dir": str(output_dir),
            "cache_dir": str(output_dir / "cache"),
        },
        "runtime": {},
        "model": {},
        "evaluation": {"explanation_span_f1_threshold": 0.5},
        "ablation": {},
    }
    config_path = tmp_path / "ea.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    summary = run_m1_effect_gate(load_ea_config(config_path))
    assert summary["status"] == "m1_effect_gate_complete"
    rows = read_jsonl(output_dir / "m1-test" / "viewpoint_effects.jsonl")
    assert len(rows) == 1
    assert rows[0]["canonical_effect_id"].startswith("ce_")
    assert summary["ready_for_pilot"] is False
