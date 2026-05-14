"""Tests for verification/faithfulness_verifier.py — pure functions (no LLM needed)."""

import json

import pytest

from episoa.verification.faithfulness_verifier import (
    ALLOWED_ISSUE_FLAGS,
    FaithfulnessVerifier,
    build_summary,
    chain_stages_by_event,
    claim_supported_by_evidence,
    clamp_float,
    contains_any,
    extract_json_object,
    fallback_verification_row,
    format_evidence_blocks,
    loose_contains,
    meaningful_tokens,
    normalize_issue_flags,
    normalize_string_list,
    parse_verifier_response,
    resolve_candidate_evidence,
    rule_precheck,
    select_candidate_tuples,
    stakeholder_aliases,
    stakeholder_supported_by_evidence,
    truncate_text,
    verified_tuple_row,
    write_verifier_table,
)


# ---------------------------------------------------------------------------
# helpers (mirror existing test patterns)
# ---------------------------------------------------------------------------

class FakeLLMResponse:
    def __init__(self, content, response_id="fake-1"):
        self.content = content
        self.response_id = response_id


def candidate_row(event_id="E001", tuple_id="E001_SOA_001", **overrides):
    row = {
        "event_id": event_id,
        "tuple_id": tuple_id,
        "stakeholder": "家长",
        "opinion": "家长对食堂安全问题表示不满并要求学校加强监管",
        "sentiment": "negative",
        "rationale": "家长通过网络渠道反映学校食堂出现异物",
        "evidence_ids": ["ev-1", "ev-2"],
        "event_chain_stage": "response",
    }
    row.update(overrides)
    return row


def evidence_row(evidence_id="ev-1", text="学校食堂安全检查报告指出存在卫生问题", source="官方", **overrides):
    row = {
        "evidence_id": evidence_id,
        "event_id": "E001",
        "text": text,
        "source": source,
        "domain": "gov.cn",
        "title": "关于食堂安全问题的通报",
        "url": "https://gov.cn/report",
        "publish_time": "2025-01-15",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# rule_precheck
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_rule_precheck_missing_evidence():
    flags = rule_precheck(
        candidate=candidate_row(evidence_ids=["ev-missing"]),
        evidence_items=[],
        missing_evidence_ids=["ev-missing"],
        chain_stages_by_event={},
    )
    assert "missing_evidence" in flags


@pytest.mark.unit
def test_rule_precheck_weak_evidence():
    flags = rule_precheck(
        candidate=candidate_row(),
        evidence_items=[evidence_row("ev-1", text="")],
        missing_evidence_ids=[],
        chain_stages_by_event={},
    )
    assert "weak_evidence" in flags


@pytest.mark.unit
def test_rule_precheck_stakeholder_not_supported():
    flags = rule_precheck(
        candidate=candidate_row(stakeholder="外星生物调查组"),
        evidence_items=[evidence_row("ev-1", text="学校食堂安全检查报告")],
        missing_evidence_ids=[],
        chain_stages_by_event={},
    )
    assert "stakeholder_not_supported" in flags


@pytest.mark.unit
def test_rule_precheck_rationale_not_supported():
    flags = rule_precheck(
        candidate=candidate_row(rationale="外星文明介入调查"),
        evidence_items=[evidence_row("ev-1", text="学校食堂安全检查报告")],
        missing_evidence_ids=[],
        chain_stages_by_event={},
    )
    assert "rationale_not_supported" in flags


@pytest.mark.unit
def test_rule_precheck_media_positive_sentiment_flag():
    flags = rule_precheck(
        candidate=candidate_row(stakeholder="媒体", sentiment="positive"),
        evidence_items=[evidence_row("ev-1", text="媒体报道学校食堂安全问题")],
        missing_evidence_ids=[],
        chain_stages_by_event={},
    )
    assert "media_comment_should_be_neutral" in flags


@pytest.mark.unit
def test_rule_precheck_official_positive_sentiment_flag():
    flags = rule_precheck(
        candidate=candidate_row(stakeholder="住建部门", sentiment="positive"),
        evidence_items=[evidence_row("ev-1", text="住建部门发布通告")],
        missing_evidence_ids=[],
        chain_stages_by_event={},
    )
    assert "official_action_should_be_neutral" in flags


@pytest.mark.unit
def test_rule_precheck_opinion_overgeneralized():
    flags = rule_precheck(
        candidate=candidate_row(opinion="家长强烈反对并质疑学校管理"),
        evidence_items=[evidence_row("ev-1", text="家长表示担忧")],
        missing_evidence_ids=[],
        chain_stages_by_event={},
    )
    assert "opinion_overgeneralized" in flags


@pytest.mark.unit
def test_rule_precheck_stage_mismatch():
    flags = rule_precheck(
        candidate=candidate_row(event_chain_stage="trigger"),
        evidence_items=[evidence_row("ev-1")],
        missing_evidence_ids=[],
        chain_stages_by_event={"E001": {"response", "resolution"}},
    )
    assert "stage_mismatch" in flags


@pytest.mark.unit
def test_rule_precheck_no_issues():
    flags = rule_precheck(
        candidate=candidate_row(),
        evidence_items=[evidence_row("ev-1", text="家长反映食堂问题"), evidence_row("ev-2", text="学校回应将整改")],
        missing_evidence_ids=[],
        chain_stages_by_event={"E001": {"response", "resolution"}},
    )
    assert flags == ["no_issue"]


# ---------------------------------------------------------------------------
# parse_verifier_response
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_parse_empty_response():
    result = parse_verifier_response(FakeLLMResponse(""), candidate=candidate_row(), model_name="fake")
    assert not result.parse_success
    assert "empty_llm_content" in result.parse_error


@pytest.mark.unit
def test_parse_valid_response():
    payload = {
        "tuple_id": "E001_SOA_001",
        "event_id": "E001",
        "verification_label": "supported",
        "verification_score": 0.9,
        "verification_rationale": "证据充分支持该元组",
        "supported_claims": ["食堂存在卫生问题"],
        "unsupported_claims": [],
        "evidence_quotes": ["安全检查报告指出存在卫生问题"],
        "issue_flags": [],
    }
    result = parse_verifier_response(FakeLLMResponse(json.dumps(payload)), candidate=candidate_row(), model_name="fake")
    assert result.parse_success
    assert result.row is not None
    assert result.row["verification_label"] == "supported"
    assert result.row["verification_score"] == 0.9


@pytest.mark.unit
def test_parse_wrapped_json():
    payload = {"tuple_id": "E001_SOA_001", "event_id": "E001", "verification_label": "supported", "verification_score": 0.85, "verification_rationale": "OK"}
    result = parse_verifier_response(FakeLLMResponse("```json\n" + json.dumps(payload) + "\n```"), candidate=candidate_row(), model_name="fake")
    assert result.parse_success
    assert result.row["verification_score"] == 0.85


@pytest.mark.unit
def test_parse_tuple_id_mismatch():
    payload = {"tuple_id": "WRONG", "event_id": "E001", "verification_label": "supported", "verification_score": 0.5}
    result = parse_verifier_response(FakeLLMResponse(json.dumps(payload)), candidate=candidate_row(), model_name="fake")
    assert not result.parse_success
    assert "tuple_id mismatch" in result.parse_error


@pytest.mark.unit
def test_parse_invalid_label():
    payload = {"tuple_id": "E001_SOA_001", "event_id": "E001", "verification_label": "fantasy", "verification_score": 0.5}
    result = parse_verifier_response(FakeLLMResponse(json.dumps(payload)), candidate=candidate_row(), model_name="fake")
    assert not result.parse_success
    assert "invalid verification_label" in result.parse_error


@pytest.mark.unit
def test_parse_malformed_json():
    result = parse_verifier_response(FakeLLMResponse("not json at all {{{"), candidate=candidate_row(), model_name="fake")
    assert not result.parse_success


# ---------------------------------------------------------------------------
# resolve_candidate_evidence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_resolve_evidence_found_and_missing():
    by_id = {"ev-1": evidence_row("ev-1"), "ev-2": evidence_row("ev-2")}
    items, missing = resolve_candidate_evidence(candidate_row(evidence_ids=["ev-1", "ev-missing"]), by_id)
    assert len(items) == 1
    assert items[0]["evidence_id"] == "ev-1"
    assert missing == ["ev-missing"]


@pytest.mark.unit
def test_resolve_all_missing():
    items, missing = resolve_candidate_evidence(candidate_row(evidence_ids=["ev-x"]), {})
    assert items == []
    assert missing == ["ev-x"]


# ---------------------------------------------------------------------------
# format_evidence_blocks
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_format_empty_evidence():
    assert "无可用 evidence" in format_evidence_blocks([])


@pytest.mark.unit
def test_format_evidence_with_text():
    blocks = format_evidence_blocks([evidence_row("ev-1")])
    assert "ev-1" in blocks
    assert "学校食堂安全检查报告" in blocks


# ---------------------------------------------------------------------------
# select_candidate_tuples
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_select_by_tuple_ids():
    candidates = [candidate_row(tuple_id="T1"), candidate_row(tuple_id="T2"), candidate_row(tuple_id="T3")]
    selected = select_candidate_tuples(candidates, tuple_ids=["T1", "T3"], event_ids=None, max_tuples=None)
    assert len(selected) == 2


@pytest.mark.unit
def test_select_by_event_ids():
    candidates = [candidate_row(event_id="E1"), candidate_row(event_id="E2")]
    selected = select_candidate_tuples(candidates, tuple_ids=None, event_ids=["E1"], max_tuples=None)
    assert len(selected) == 1


@pytest.mark.unit
def test_select_max_tuples():
    candidates = [candidate_row(tuple_id=f"T{i}") for i in range(10)]
    selected = select_candidate_tuples(candidates, tuple_ids=None, event_ids=None, max_tuples=3)
    assert len(selected) == 3


# ---------------------------------------------------------------------------
# chain_stages_by_event
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_chain_stages_by_event():
    chains = [
        {"event_id": "E001", "stages": [{"stage": "trigger"}, {"stage": "response"}]},
        {"event_id": "E002", "stages": [{"stage": "diffusion"}]},
    ]
    result = chain_stages_by_event(chains)
    assert result["E001"] == {"trigger", "response"}
    assert result["E002"] == {"diffusion"}


@pytest.mark.unit
def test_chain_stages_by_event_last_wins_same_event():
    """Current behavior: same event_id overwrites previous stages (does not union)."""
    chains = [
        {"event_id": "E001", "stages": [{"stage": "trigger"}]},
        {"event_id": "E001", "stages": [{"stage": "resolution"}]},
    ]
    result = chain_stages_by_event(chains)
    assert result["E001"] == {"resolution"}


@pytest.mark.unit
def test_chain_stages_empty():
    assert chain_stages_by_event([]) == {}


# ---------------------------------------------------------------------------
# normalize_issue_flags
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_normalize_flags_dedup_and_filter():
    result = normalize_issue_flags(["missing_evidence", "missing_evidence", "no_issue", "garbage"])
    assert result == ["missing_evidence"]


@pytest.mark.unit
def test_normalize_flags_default():
    result = normalize_issue_flags([])
    assert result == ["no_issue"]


# ---------------------------------------------------------------------------
# normalize_string_list
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_normalize_string_list():
    result = normalize_string_list(["a", "b", "c", "d", "e"], max_items=3, max_chars=10)
    assert result == ["a", "b", "c"]


@pytest.mark.unit
def test_normalize_string_list_non_list():
    assert normalize_string_list("not a list", max_items=5, max_chars=10) == []


# ---------------------------------------------------------------------------
# extract_json_object
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_extract_json_plain():
    assert extract_json_object('{"a": 1}') == '{"a": 1}'


@pytest.mark.unit
def test_extract_json_markdown_fence():
    result = extract_json_object("```json\n{\"a\": 1}\n```")
    assert result == '{"a": 1}'


@pytest.mark.unit
def test_extract_json_from_text():
    result = extract_json_object("some text {\"a\": 1} more text")
    assert result == '{"a": 1}'


@pytest.mark.unit
def test_extract_json_no_object():
    with pytest.raises(ValueError):
        extract_json_object("no json here")


# ---------------------------------------------------------------------------
# stakeholder_aliases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stakeholder_aliases_government():
    aliases = stakeholder_aliases("政府部门")
    assert any("政府" in a for a in aliases)


@pytest.mark.unit
def test_stakeholder_aliases_housing():
    aliases = stakeholder_aliases("住建部门")
    assert any("住建局" in a for a in aliases)


@pytest.mark.unit
def test_stakeholder_aliases_media():
    aliases = stakeholder_aliases("媒体")
    assert any("媒体" in a for a in aliases) or len(aliases) > 0


# ---------------------------------------------------------------------------
# claim_supported_by_evidence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_claim_supported_exact_match():
    assert claim_supported_by_evidence("食堂安全问题", "食堂安全问题需要重视")


@pytest.mark.unit
def test_claim_not_supported():
    assert not claim_supported_by_evidence("外星文明", "食堂安全检查报告")


# ---------------------------------------------------------------------------
# stakeholder_supported_by_evidence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stakeholder_supported():
    assert stakeholder_supported_by_evidence("家长", "家长反映食堂问题", [evidence_row("ev-1", text="家长反映食堂问题")])


@pytest.mark.unit
def test_stakeholder_not_supported():
    assert not stakeholder_supported_by_evidence("外星人", "食堂安全检查报告", [evidence_row("ev-1", text="食堂安全检查报告")])


# ---------------------------------------------------------------------------
# loose_contains / contains_any / meaningful_tokens
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_loose_contains_exact():
    assert loose_contains("家长反映食堂问题", "家长")


@pytest.mark.unit
def test_loose_contains_not():
    assert not loose_contains("食堂安全检查报告", "家长")


@pytest.mark.unit
def test_contains_any_true():
    assert contains_any("家长反映食堂问题", ["家长", "学生"])


@pytest.mark.unit
def test_contains_any_false():
    assert not contains_any("食堂安全检查报告", ["家长", "学生"])


@pytest.mark.unit
def test_meaningful_tokens():
    tokens = meaningful_tokens("家长反映食堂安全问题")
    assert len(tokens) > 0
    assert all(isinstance(t, str) and len(t) >= 2 for t in tokens)


# ---------------------------------------------------------------------------
# truncate_text / clamp_float
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_truncate_text():
    assert truncate_text("hello world", 5) == "hello"


@pytest.mark.unit
def test_clamp_float():
    assert clamp_float(0.5) == 0.5
    assert clamp_float(1.5) == 1.0
    assert clamp_float(-0.5) == 0.0
    assert clamp_float("not a number") == 0.0


# ---------------------------------------------------------------------------
# verified_tuple_row / fallback_verification_row
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_verified_tuple_row():
    row = verified_tuple_row(
        candidate=candidate_row(),
        verification_label="supported",
        verification_score=0.9,
        verification_rationale="OK",
        supported_claims=["claim1"],
        unsupported_claims=[],
        evidence_quotes=["quote"],
        issue_flags=[],
        model_name="test",
        verifier_prompt_version="v1",
        raw_response_id="r1",
    )
    assert row["verification_label"] == "supported"
    assert row["verification_score"] == 0.9
    assert row["stakeholder"] == "家长"


@pytest.mark.unit
def test_fallback_verification_row():
    row = fallback_verification_row(
        candidate=candidate_row(),
        label="unsupported",
        score=0.0,
        rationale="no evidence",
        issue_flags=["missing_evidence"],
        model_name="test",
    )
    assert row["verification_label"] == "unsupported"
    assert "missing_evidence" in row["issue_flags"]


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_summary():
    candidates = [candidate_row(tuple_id="T1"), candidate_row(tuple_id="T2")]
    verified = [
        fallback_verification_row(c, label="supported", score=0.8, rationale="", issue_flags=[], model_name="t")
        for c in candidates
    ]
    summary = build_summary(
        candidates=candidates, verified=verified, api_calls=2, api_failures=0,
        parse_failed_tuples=[], missing_evidence_tuples=[],
        output_path="/tmp/test.jsonl", model_name="test",
    )
    assert summary["num_candidate_tuples"] == 2
    assert summary["supported_rate"] == 1.0
    assert summary["label_distribution"]["supported"] == 2


# ---------------------------------------------------------------------------
# write_verifier_table
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_write_verifier_table(tmp_path):
    rows = [fallback_verification_row(candidate_row(), label="supported", score=0.9, rationale="OK", issue_flags=[], model_name="t")]
    path = tmp_path / "verifier_table.csv"
    write_verifier_table(path, rows)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "verification_label" in content
    assert "supported" in content


# ---------------------------------------------------------------------------
# FaithfulnessVerifier.build_prompt
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_verifier_build_prompt():
    verifier = FaithfulnessVerifier(llm_client=None, model_name="fake")
    system, user = verifier.build_prompt(
        candidate=candidate_row(),
        evidence_items=[evidence_row("ev-1")],
        precheck_flags=[],
    )
    assert "strict evidence faithfulness verifier" in system
    assert "E001_SOA_001" in user
    assert "ev-1" in user


@pytest.mark.unit
def test_verifier_verify_tuple_dry_run():
    verifier = FaithfulnessVerifier(llm_client=None, model_name="fake")
    by_id = {"ev-1": evidence_row("ev-1"), "ev-2": evidence_row("ev-2")}
    row, record = verifier.verify_tuple(candidate=candidate_row(), evidence_by_id=by_id, dry_run=True)
    assert row["verification_label"] in ("unclear", "unsupported")
    assert record["dry_run"] is True


@pytest.mark.unit
def test_verifier_verify_tuple_no_evidence():
    verifier = FaithfulnessVerifier(llm_client=None, model_name="fake")
    row, record = verifier.verify_tuple(candidate=candidate_row(evidence_ids=["ev-missing"]), evidence_by_id={})
    assert row["verification_label"] == "unsupported"
    assert "missing_evidence" in row["issue_flags"]
