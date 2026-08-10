from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from episoa.data.loader import read_typed_jsonl, write_jsonl
from episoa.ea.commands import prepare_ea, run_ea
from episoa.ea.extraction import (
    EFFECT_EXTRACTION_SYSTEM_PROMPT,
    chunk_document,
    extract_effect_candidates,
)
from episoa.ea.preparation import validate_document_registry
from episoa.ea.schema import (
    DocumentRecord,
    EffectExtractionResponse,
    SourceRecord,
    content_hash,
)


class ScriptedClient:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        content = self.responses.pop(0)
        return SimpleNamespace(content=content, response_id=f"R{len(self.calls)}")


def _source(source_id: str = "SRC001", name: str = "测试媒体") -> dict:
    return {"source_id": source_id, "source_name": name, "source_type": "news"}


def _raw_document(
    document_id: str = "D001",
    *,
    event_id: str = "E001",
    body_text: str = "业主反对补偿方案。",
    source_id: str = "SRC001",
    **updates,
) -> dict:
    row = {
        "document_id": document_id,
        "event_id": event_id,
        "reporting_source": _source(source_id, f"媒体-{source_id}"),
        "derivation_type": "original",
        "body_text": body_text,
        "content_kind": "full_text",
    }
    row.update(updates)
    return row


def _document(
    document_id: str, text: str, *, event_id: str = "E001", source_id: str = "SRC001"
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        event_id=event_id,
        reporting_source_id=source_id,
        primary_source_id=source_id,
        derivation_type="original",
        content_hash=content_hash(text),
        normalized_text=text,
    )


def _effect_payload(
    text: str,
    *,
    stakeholder: str,
    type_cue: str,
    value_cue: str,
    target_cue: str,
    effect_type: str,
    effect_value: str,
    effect_surface: str,
) -> dict:
    cues = {
        "holder_surface": stakeholder,
        "stakeholder_category": stakeholder,
        "effect_type": type_cue,
        "effect_value": value_cue,
        "target": target_cue,
        "effect_stage": text,
    }
    spans = []
    for field, cue in cues.items():
        start = text.index(cue)
        spans.append(
            {
                "support_field": field,
                "char_start": start,
                "char_end": start + len(cue),
                "span_text": cue,
            }
        )
    payload = {
        "stakeholder_category": "affected_public",
        "holder_surface": stakeholder,
        "holder_role": stakeholder,
        "effect_type": effect_type,
        "effect_surface": effect_surface,
        "effect_value": effect_value,
        "target": target_cue,
        "effect_stage": "conflict",
        "expression_present": True,
        "evidence_spans": spans,
    }
    if effect_type == "emotion":
        payload["emotion_state_present"] = True
    return payload


def _stance_payload(text: str = "业主反对补偿方案。") -> dict:
    return _effect_payload(
        text,
        stakeholder="业主",
        type_cue="反对",
        value_cue="反对",
        target_cue="补偿方案",
        effect_type="stance",
        effect_value="oppose",
        effect_surface="反对补偿方案",
    )


def _config_path(tmp_path: Path, *, chunk_size: int = 6000, overlap: int = 300) -> Path:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    config = {
        "run_id": "m2-test",
        "mode": "ea_pilot",
        "data": {
            "raw_posts_path": str(data_dir / "raw.jsonl"),
            "sources_path": str(data_dir / "sources.jsonl"),
            "documents_path": str(data_dir / "documents.jsonl"),
            "effect_candidates_path": str(data_dir / "process" / "effects.jsonl"),
            "explanation_candidates_path": str(
                data_dir / "process" / "explanations.jsonl"
            ),
            "relation_judgments_path": str(data_dir / "process" / "relations.jsonl"),
            "evidence_links_path": str(data_dir / "process" / "links.jsonl"),
            "extraction_attempts_path": str(data_dir / "process" / "attempts.jsonl"),
            "m3_attempts_path": str(data_dir / "process" / "m3_attempts.jsonl"),
            "verification_diagnostics_path": str(
                data_dir / "process" / "verification.jsonl"
            ),
            "viewpoint_effects_path": str(
                data_dir / "formal" / "viewpoint_effects.jsonl"
            ),
            "attribution_claims_path": str(
                data_dir / "formal" / "attribution_claims.jsonl"
            ),
            "canonical_claim_groups_path": str(
                data_dir / "formal" / "canonical_claim_groups.jsonl"
            ),
            "canonical_adjudication_queue_path": str(
                data_dir / "process" / "canonical_adjudication_queue.jsonl"
            ),
        },
        "output": {
            "runs_dir": str(output_dir / "runs"),
            "cache_dir": str(output_dir / "cache"),
        },
        "runtime": {
            "chunk_size_chars": chunk_size,
            "chunk_overlap_chars": overlap,
            "schema_retries": 1,
        },
        "model": {},
        "evaluation": {"explanation_span_f1_threshold": 0.5},
        "ablation": {},
    }
    path = tmp_path / "ea.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


def test_prepare_ea_builds_traceable_sources_documents_and_hashes(
    tmp_path: Path,
) -> None:
    config_path = _config_path(tmp_path)
    raw_path = tmp_path / "data" / "raw.jsonl"
    write_jsonl(
        raw_path,
        [
            _raw_document("D001"),
            _raw_document(
                "D002",
                body_text="媒体转载了业主的表态。",
                source_id="SRC002",
                primary_source=_source("SRC001", "媒体-SRC001"),
                parent_document_id="D001",
                derivation_type="syndicated_copy",
            ),
        ],
    )

    result = prepare_ea(config_path)

    assert result["status"] == "m2_documents_prepared"
    sources = read_typed_jsonl(tmp_path / "data" / "sources.jsonl", SourceRecord)
    documents = read_typed_jsonl(tmp_path / "data" / "documents.jsonl", DocumentRecord)
    assert {row.source_id for row in sources} == {"SRC001", "SRC002"}
    by_id = {row.document_id: row for row in documents}
    assert by_id["D002"].primary_source_id == "SRC001"
    assert by_id["D002"].parent_document_id == "D001"
    assert by_id["D001"].content_hash == content_hash(by_id["D001"].normalized_text)


@pytest.mark.parametrize(
    "updates, expected",
    [
        ({"body_text": "  \n "}, "empty"),
        ({"content_kind": "summary"}, "summary content"),
        ({"summary_text": "业主反对补偿方案。"}, "masquerading"),
        ({"declared_content_hash": "sha256:wrong"}, "does not match"),
        ({"parent_document_id": "D999"}, "parent_document_id is not present"),
    ],
)
def test_prepare_ea_rejects_document_quality_failures(
    tmp_path: Path, updates: dict, expected: str
) -> None:
    config_path = _config_path(tmp_path)
    write_jsonl(tmp_path / "data" / "raw.jsonl", [_raw_document(**updates)])

    result = prepare_ea(config_path)

    assert result["status"] == "invalid_input"
    assert expected in result["reason"]
    assert not (tmp_path / "data" / "documents.jsonl").exists()


def test_document_registry_rejects_dangling_sources() -> None:
    with pytest.raises(ValueError, match="reporting_source_id is dangling"):
        validate_document_registry([], [_document("D001", "业主反对补偿方案。")])


def test_conflicting_same_event_documents_are_never_mixed() -> None:
    left_text = "业主反对补偿方案。"
    right_text = "企业支持补偿方案。"
    left = _document("D001", left_text, source_id="SRC001")
    right = _document("D002", right_text, source_id="SRC002")
    right_payload = _effect_payload(
        right_text,
        stakeholder="企业",
        type_cue="支持",
        value_cue="支持",
        target_cue="补偿方案",
        effect_type="stance",
        effect_value="support",
        effect_surface="支持补偿方案",
    )
    client = ScriptedClient(
        [
            json.dumps({"effects": [_stance_payload(left_text)]}, ensure_ascii=False),
            json.dumps({"effects": [right_payload]}, ensure_ascii=False),
        ]
    )

    result = extract_effect_candidates([left, right], client)

    assert [row.document_id for row in result.candidates] == ["D001", "D002"]
    first_prompt = json.loads(client.calls[0]["user_prompt"])
    second_prompt = json.loads(client.calls[1]["user_prompt"])
    assert first_prompt["document_id"] == "D001"
    assert second_prompt["document_id"] == "D002"
    assert right_text not in first_prompt["chunk_text"]
    assert left_text not in second_prompt["chunk_text"]


def test_long_document_chunks_keep_provenance_and_absolute_span_round_trip() -> None:
    text = "甲" * 12 + "业主反对补偿方案。" + "乙" * 12
    document = _document("D-LONG", text)
    chunks = chunk_document(document, chunk_size_chars=20, chunk_overlap_chars=10)
    responses = []
    for chunk in chunks:
        if "业主反对补偿方案。" in chunk.text:
            responses.append(
                json.dumps(
                    {"effects": [_stance_payload(chunk.text)]}, ensure_ascii=False
                )
            )
        else:
            responses.append('{"effects": []}')
    client = ScriptedClient(responses)

    result = extract_effect_candidates(
        [document],
        client,
        chunk_size_chars=20,
        chunk_overlap_chars=10,
    )

    assert result.candidates
    assert {row.document_id for row in result.candidates} == {"D-LONG"}
    assert {row.document_id for row in result.attempts} == {"D-LONG"}
    for link in result.evidence_links:
        assert text[link.char_start : link.char_end] == link.span_text


def test_four_negative_constraints_are_in_prompt_and_fact_only_docs_emit_nothing() -> (
    None
):
    assert "无立场表达时，不创建stance" in EFFECT_EXTRACTION_SYSTEM_PROMPT
    assert "无情绪表达时，不创建emotion" in EFFECT_EXTRACTION_SYSTEM_PROMPT
    assert "uncertain仅表示确有立场或情绪表达" in EFFECT_EXTRACTION_SYSTEM_PROMPT
    assert "纯事实陈述不能创建Emotion" in EFFECT_EXTRACTION_SYSTEM_PROMPT
    documents = [
        _document("D-FACT-1", "会议于周一举行。"),
        _document("D-FACT-2", "公告于网站发布。"),
    ]
    result = extract_effect_candidates(
        documents, ScriptedClient(['{"effects": []}', '{"effects": []}'])
    )
    assert result.candidates == ()
    assert result.evidence_links == ()


def test_neutral_emotion_and_uncertain_require_expression_assertions() -> None:
    neutral_text = "居民对结果感到平静。"
    neutral = _effect_payload(
        neutral_text,
        stakeholder="居民",
        type_cue="感到平静",
        value_cue="平静",
        target_cue="结果",
        effect_type="emotion",
        effect_value="neutral",
        effect_surface="感到平静",
    )
    EffectExtractionResponse.model_validate({"effects": [neutral]})

    without_emotion_state = dict(neutral)
    without_emotion_state.pop("emotion_state_present")
    with pytest.raises(ValidationError, match="expressed emotion state"):
        EffectExtractionResponse.model_validate({"effects": [without_emotion_state]})

    uncertain = _stance_payload()
    uncertain["effect_value"] = "uncertain"
    EffectExtractionResponse.model_validate({"effects": [uncertain]})
    without_expression = dict(uncertain)
    without_expression.pop("expression_present")
    with pytest.raises(ValidationError):
        EffectExtractionResponse.model_validate({"effects": [without_expression]})


def test_invalid_llm_schema_gets_one_deterministic_document_local_retry() -> None:
    text = "业主反对补偿方案。"
    client = ScriptedClient(
        [
            '{"effects": [{"effect_type": "stance"}]}',
            json.dumps({"effects": [_stance_payload(text)]}, ensure_ascii=False),
        ]
    )

    result = extract_effect_candidates([_document("D001", text)], client)

    assert [row.valid for row in result.attempts] == [False, True]
    assert len(client.calls) == 2
    first = json.loads(client.calls[0]["user_prompt"])
    second = json.loads(client.calls[1]["user_prompt"])
    assert first["document_id"] == second["document_id"] == "D001"
    assert first["chunk_text"] == second["chunk_text"] == text
    assert "previous_validation_error" in second


def test_multiple_effects_in_one_text_remain_atomic() -> None:
    text = "业主反对补偿方案并拒绝签约。"
    stance = _stance_payload(text)
    action = _effect_payload(
        text,
        stakeholder="业主",
        type_cue="拒绝签约",
        value_cue="拒绝签约",
        target_cue="签约",
        effect_type="action",
        effect_value="拒绝签约",
        effect_surface="拒绝签约",
    )
    client = ScriptedClient(
        [json.dumps({"effects": [stance, action]}, ensure_ascii=False)]
    )

    result = extract_effect_candidates([_document("D001", text)], client)

    assert len(result.candidates) == 2
    assert {row.effect_type for row in result.candidates} == {"stance", "action"}


def test_run_ea_writes_only_m2_candidates_and_no_formal_or_canonical_rows(
    tmp_path: Path,
) -> None:
    config_path = _config_path(tmp_path)
    write_jsonl(tmp_path / "data" / "raw.jsonl", [_raw_document()])
    assert prepare_ea(config_path)["status"] == "m2_documents_prepared"
    client = ScriptedClient(
        [json.dumps({"effects": [_stance_payload()]}, ensure_ascii=False)]
    )

    result = run_ea(config_path, stage="m2", llm_client=client)

    assert result["status"] == "m2_effect_extraction_complete"
    assert result["formal_effects_created"] == 0
    assert result["canonical_records_created"] == 0
    run_dir = tmp_path / "outputs" / "runs" / "m2-test"
    assert (run_dir / "effect_candidates.jsonl").is_file()
    assert not (run_dir / "viewpoint_effects.jsonl").exists()
    assert not (run_dir / "canonical_adjudication_queue.jsonl").exists()
