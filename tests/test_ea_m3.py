from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from episoa.data.loader import read_typed_jsonl, write_jsonl
from episoa.ea.config import EAConfig
from episoa.ea.m3 import M3Clients, run_m3_core
from episoa.ea.pipeline import run_m3_pipeline
from episoa.ea.schema import (
    AttributionClaim,
    DocumentRecord,
    EffectCandidateRecord,
    EvidenceLink,
    SourceRecord,
    content_hash,
)


class ScriptedClient:
    def __init__(self, responses: list[dict]):
        self.responses = [json.dumps(row, ensure_ascii=False) for row in responses]
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        content = self.responses.pop(0)
        return SimpleNamespace(content=content, response_id=f"R{len(self.calls)}")


def _span(text: str, field: str, cue: str) -> dict:
    start = text.index(cue)
    return {
        "support_field": field,
        "char_start": start,
        "char_end": start + len(cue),
        "span_text": cue,
    }


def _document(
    document_id: str,
    text: str,
    *,
    source_id: str = "SRC-MEDIA",
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        event_id="E001",
        reporting_source_id=source_id,
        primary_source_id=source_id,
        derivation_type="original",
        content_hash=content_hash(text),
        normalized_text=text,
    )


def _effect(
    document: DocumentRecord,
    *,
    effect_id: str,
    holder_cue: str = "业主",
    effect_type: str = "stance",
    effect_surface: str = "反对方案",
    effect_value: str = "oppose",
    target: str = "方案",
    stakeholder_category: str = "affected_public",
) -> EffectCandidateRecord:
    return EffectCandidateRecord(
        effect_id=effect_id,
        event_id=document.event_id,
        document_id=document.document_id,
        reporting_source_id=document.reporting_source_id,
        primary_source_id=document.primary_source_id,
        derivation_type=document.derivation_type,
        stakeholder_category=stakeholder_category,
        holder_surface=holder_cue,
        holder_role=holder_cue,
        effect_type=effect_type,
        effect_surface=effect_surface,
        effect_value=effect_value,
        target=target,
        effect_stage="conflict",
    )


def _effect_links(
    document: DocumentRecord,
    effect: EffectCandidateRecord,
    *,
    holder_cue: str = "业主",
    type_cue: str = "反对",
    value_cue: str = "反对",
    target_cue: str = "方案",
) -> list[EvidenceLink]:
    cues = {
        "holder_surface": holder_cue,
        "stakeholder_category": holder_cue,
        "effect_type": type_cue,
        "effect_value": value_cue,
        "target": target_cue,
        "effect_stage": document.normalized_text,
    }
    output = []
    for index, (field, cue) in enumerate(cues.items(), start=1):
        start = document.normalized_text.index(cue)
        output.append(
            EvidenceLink(
                evidence_link_id=f"EL-{effect.effect_id}-{index}",
                target_type="effect",
                target_id=effect.effect_id,
                document_id=document.document_id,
                evidence_id=f"EV-{document.document_id}",
                span_id=f"SP-{effect.effect_id}-{index}",
                char_start=start,
                char_end=start + len(cue),
                span_text=cue,
                support_field=field,
                support_label="supports",
            )
        )
    return output


def _explanation(text: str, phrase: str, *, source: str = "explicit_cue") -> dict:
    return {
        "explanation_surface": phrase,
        "normalized_explanation": phrase,
        "candidate_source": source,
        "evidence_spans": [_span(text, "explanation_surface", phrase)],
    }


def _relation(
    text: str,
    *,
    effect_type: str = "stance",
    decision: str = "supported",
    explanation_cue: str,
    holder_cue: str = "业主",
    attribution_holder_category: str = "affected_public",
    attribution_holder_role: str | None = "业主",
    explicitness: str = "explicit",
    certainty: str = "certain",
    polarity: str = "affirmed",
    relation_cue: str = "因",
    certainty_cue: str | None = None,
    polarity_cue: str | None = None,
) -> dict:
    relation_types = {
        "stance": "stance_rationale",
        "emotion": "emotion_trigger",
        "action": "action_motivation",
    }
    if decision == "no_relation":
        return {
            "judgment": {
                "relation_decision": "no_relation",
                "relation_type": None,
                "attribution_holder_category": attribution_holder_category,
                "attribution_holder_surface": None,
                "attribution_holder_role": attribution_holder_role,
                "claim_stage": "follow_up",
                "explicitness": explicitness,
                "certainty": certainty,
                "polarity": polarity,
                "evidence_spans": [],
            }
        }
    certainty_cue = certainty_cue or relation_cue
    polarity_cue = polarity_cue or relation_cue
    spans = [
        _span(text, "explanation_surface", explanation_cue),
        _span(text, "relation_type", relation_cue),
        _span(text, "attribution_holder_category", holder_cue),
        _span(text, "explicitness", relation_cue),
        _span(text, "certainty", certainty_cue),
        _span(text, "polarity", polarity_cue),
        _span(text, "attribution_holder_surface", holder_cue),
    ]
    return {
        "judgment": {
            "relation_decision": "supported",
            "relation_type": relation_types[effect_type],
            "attribution_holder_category": attribution_holder_category,
            "attribution_holder_surface": holder_cue,
            "attribution_holder_role": attribution_holder_role,
            "claim_stage": "conflict",
            "explicitness": explicitness,
            "certainty": certainty,
            "polarity": polarity,
            "evidence_spans": spans,
        }
    }


def _effect_verification(**updates) -> dict:
    row = {
        "holder_surface": "verified",
        "stakeholder_category": "verified",
        "effect_type": "verified",
        "effect_value": "verified",
        "target": "verified",
        "effect_stage": "verified",
    }
    row.update(updates)
    return row


def _claim_verification(**updates) -> dict:
    row = {
        "effect_grounded": "verified",
        "explanation_grounded": "verified",
        "relation_grounded": "verified",
        "direction_correct": "verified",
        "effect_holder_grounded": "verified",
        "attribution_holder_grounded": "verified",
        "certainty_correct": "verified",
        "polarity_correct": "verified",
    }
    row.update(updates)
    return row


def test_explicit_same_holder_claim_is_promoted_with_dual_attribution() -> None:
    text = "业主称因补偿标准过低而反对方案。"
    document = _document("D001", text)
    effect = _effect(document, effect_id="EF001")
    explanation_client = ScriptedClient(
        [{"candidates": [_explanation(text, "补偿标准过低")]}]
    )
    relation_client = ScriptedClient([_relation(text, explanation_cue="补偿标准过低")])
    verifier_client = ScriptedClient([_effect_verification(), _claim_verification()])

    result = run_m3_core(
        documents=[document],
        effect_candidates=[effect],
        effect_evidence_links=_effect_links(document, effect),
        clients=M3Clients(explanation_client, relation_client, verifier_client),
    )

    assert len(result.effect_promotion.formal_effects) == 1
    assert result.effect_promotion.formal_effects[0].canonical_effect_id is None
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.attribution_holder_category == effect.stakeholder_category
    assert claim.reporting_source_id == "SRC-MEDIA"
    assert claim.attribution_holder_category != claim.reporting_source_id
    assert claim.explicitness == "explicit"
    assert claim.certainty == "certain"
    assert claim.polarity == "affirmed"
    assert "relation_decision" not in claim.model_dump()
    assert claim.canonical_claim_group_id is None
    assert {
        row.support_field for row in result.evidence_links if row.target_type == "claim"
    } == {
        "explanation_surface",
        "relation_type",
        "attribution_holder_surface",
        "attribution_holder_category",
        "explicitness",
        "certainty",
        "polarity",
    }


def test_m3_rejects_cross_document_effect_evidence_before_llm_calls() -> None:
    left = _document("D001", "业主反对方案。")
    right = _document("D002", "业主反对方案。")
    effect = _effect(left, effect_id="EF001")
    crossed_links = [
        row.model_copy(update={"document_id": "D002"})
        for row in _effect_links(left, effect)
    ]
    clients = M3Clients(ScriptedClient([]), ScriptedClient([]), ScriptedClient([]))

    with pytest.raises(ValueError, match="crosses document boundary"):
        run_m3_core(
            documents=[left, right],
            effect_candidates=[effect],
            effect_evidence_links=crossed_links,
            clients=clients,
        )


def test_cross_sentence_implicit_claim_keeps_distinct_attribution_holder() -> None:
    text = "居民表示担忧。专家称这并非由施工噪声引起，原因仍无法确定。"
    document = _document("D001", text)
    effect = _effect(
        document,
        effect_id="EF001",
        holder_cue="居民",
        effect_type="emotion",
        effect_surface="担忧",
        effect_value="negative",
        target="施工噪声",
    )
    links = _effect_links(
        document,
        effect,
        holder_cue="居民",
        type_cue="担忧",
        value_cue="担忧",
        target_cue="施工噪声",
    )
    explanation_client = ScriptedClient(
        [{"candidates": [_explanation(text, "施工噪声", source="cross_sentence")]}]
    )
    relation_client = ScriptedClient(
        [
            _relation(
                text,
                effect_type="emotion",
                explanation_cue="施工噪声",
                holder_cue="专家",
                attribution_holder_category="expert",
                attribution_holder_role="专家",
                explicitness="implicit",
                certainty="uncertain",
                polarity="denied",
                relation_cue="由",
                certainty_cue="无法确定",
                polarity_cue="并非",
            )
        ]
    )
    verifier_client = ScriptedClient([_effect_verification(), _claim_verification()])

    result = run_m3_core(
        documents=[document],
        effect_candidates=[effect],
        effect_evidence_links=links,
        clients=M3Clients(explanation_client, relation_client, verifier_client),
    )

    claim = result.claims[0]
    assert result.explanation_candidates[0].candidate_source == "cross_sentence"
    assert claim.attribution_holder_category == "expert"
    assert claim.attribution_holder_category != effect.stakeholder_category
    assert claim.explicitness == "implicit"
    assert claim.certainty == "uncertain"
    assert claim.polarity == "denied"


def test_temporally_adjacent_candidate_can_be_no_relation() -> None:
    text = "业主反对方案。次日天气转晴。"
    document = _document("D001", text)
    effect = _effect(document, effect_id="EF001")
    explanation_client = ScriptedClient(
        [
            {
                "candidates": [
                    _explanation(text, "次日天气转晴", source="temporal_compatible")
                ]
            }
        ]
    )
    relation_client = ScriptedClient(
        [
            _relation(
                text,
                decision="no_relation",
                explanation_cue="次日天气转晴",
            )
        ]
    )
    verifier_client = ScriptedClient([_effect_verification(), _claim_verification()])

    result = run_m3_core(
        documents=[document],
        effect_candidates=[effect],
        effect_evidence_links=_effect_links(document, effect),
        clients=M3Clients(explanation_client, relation_client, verifier_client),
    )

    assert result.relation_judgments[0].relation_decision == "no_relation"
    assert result.claims == ()
    assert result.claim_failures[0].reasons == ("relation_decision:no_relation",)


def test_rejected_and_insufficient_claims_never_enter_formal_claims() -> None:
    text = "业主因补偿偏低反对方案，报道同时提到天气变化。"
    document = _document("D001", text)
    effect = _effect(document, effect_id="EF001")
    explanations = [
        _explanation(text, "补偿偏低"),
        _explanation(text, "天气变化", source="llm_proposed"),
    ]
    explanation_client = ScriptedClient([{"candidates": explanations}])
    relation_client = ScriptedClient(
        [
            _relation(text, explanation_cue="补偿偏低"),
            _relation(text, explanation_cue="天气变化"),
        ]
    )
    verifier_client = ScriptedClient(
        [
            _effect_verification(),
            _claim_verification(relation_grounded="rejected"),
            _claim_verification(explanation_grounded="insufficient"),
        ]
    )

    result = run_m3_core(
        documents=[document],
        effect_candidates=[effect],
        effect_evidence_links=_effect_links(document, effect),
        clients=M3Clients(explanation_client, relation_client, verifier_client),
    )

    statuses = [
        row.status
        for row in result.verification_diagnostics
        if row.target_type == "claim"
    ]
    assert statuses == ["rejected", "insufficient"]
    assert result.claims == ()
    assert len(result.claim_failures) == 2


def test_m3_stops_at_verified_source_records_without_canonical_ids() -> None:
    specs = [
        ("D001", "业主称因补偿标准过低而反对方案。", "补偿标准过低", "affirmed"),
        ("D002", "业主称因补偿标准过低而反对方案。", "补偿标准过低", "affirmed"),
        (
            "D003",
            "业主称因补偿标准明显过低而反对方案。",
            "补偿标准明显过低",
            "affirmed",
        ),
        (
            "D004",
            "业主称并非因补偿标准过低而反对方案。",
            "补偿标准过低",
            "denied",
        ),
    ]
    documents = [_document(doc_id, text) for doc_id, text, _, _ in specs]
    effects = [
        _effect(document, effect_id=f"EF{index:03d}")
        for index, document in enumerate(documents, start=1)
    ]
    links = [
        link
        for document, effect in zip(documents, effects, strict=True)
        for link in _effect_links(document, effect)
    ]
    explanation_client = ScriptedClient(
        [{"candidates": [_explanation(text, phrase)]} for _, text, phrase, _ in specs]
    )
    relation_client = ScriptedClient(
        [
            _relation(
                text,
                explanation_cue=phrase,
                polarity=polarity,
                polarity_cue="并非" if polarity == "denied" else "因",
            )
            for _, text, phrase, polarity in specs
        ]
    )
    verifier_client = ScriptedClient(
        [
            *[_effect_verification() for _ in effects],
            *[_claim_verification() for _ in effects],
        ]
    )

    result = run_m3_core(
        documents=documents,
        effect_candidates=effects,
        effect_evidence_links=links,
        clients=M3Clients(explanation_client, relation_client, verifier_client),
    )

    assert len(result.effect_promotion.formal_effects) == 4
    assert len(result.claims) == 4
    assert all(row.canonical_effect_id is None for row in result.effect_promotion.formal_effects)
    assert all(row.canonical_claim_group_id is None for row in result.claims)


def test_m3_pipeline_materializes_only_formal_verified_outputs(tmp_path: Path) -> None:
    text = "业主称因补偿标准过低而反对方案。"
    document = _document("D001", text)
    effect = _effect(document, effect_id="EF001")
    data_dir = tmp_path / "data"
    write_jsonl(
        data_dir / "sources.jsonl",
        [
            SourceRecord(
                source_id="SRC-MEDIA", source_name="测试媒体", source_type="news"
            )
        ],
    )
    write_jsonl(data_dir / "documents.jsonl", [document])
    write_jsonl(data_dir / "effects.jsonl", [effect])
    write_jsonl(data_dir / "links.jsonl", _effect_links(document, effect))
    paths = {
        "raw_posts_path": str(data_dir / "raw.jsonl"),
        "sources_path": str(data_dir / "sources.jsonl"),
        "documents_path": str(data_dir / "documents.jsonl"),
        "effect_candidates_path": str(data_dir / "effects.jsonl"),
        "explanation_candidates_path": str(data_dir / "explanations.jsonl"),
        "relation_judgments_path": str(data_dir / "relations.jsonl"),
        "evidence_links_path": str(data_dir / "links.jsonl"),
        "extraction_attempts_path": str(data_dir / "m2_attempts.jsonl"),
        "m3_attempts_path": str(data_dir / "m3_attempts.jsonl"),
        "verification_diagnostics_path": str(data_dir / "verification.jsonl"),
        "viewpoint_effects_path": str(data_dir / "formal_effects.jsonl"),
        "attribution_claims_path": str(data_dir / "formal_claims.jsonl"),
        "canonical_claim_groups_path": str(data_dir / "groups.jsonl"),
        "canonical_adjudication_queue_path": str(data_dir / "adjudication.jsonl"),
    }
    config = EAConfig(
        run_id="m3-test",
        mode="ea_pilot",
        data=paths,
        output={
            "runs_dir": str(tmp_path / "outputs" / "runs"),
            "cache_dir": str(tmp_path / "outputs" / "cache"),
        },
        runtime={"schema_retries": 1},
    )
    clients = M3Clients(
        ScriptedClient([{"candidates": [_explanation(text, "补偿标准过低")]}]),
        ScriptedClient([_relation(text, explanation_cue="补偿标准过低")]),
        ScriptedClient([_effect_verification(), _claim_verification()]),
    )

    summary = run_m3_pipeline(config, clients)

    assert summary["status"] == "m3_core_complete"
    assert summary["claim_pairs_created"] == 0
    claims = read_typed_jsonl(paths["attribution_claims_path"], AttributionClaim)
    assert len(claims) == 1
    assert claims[0].canonical_claim_group_id is None
    assert not Path(paths["canonical_claim_groups_path"]).exists()
    assert not Path(paths["raw_posts_path"]).exists()
