import json

from episoa.verification.faithfulness_verifier import (
    FaithfulnessVerifier,
    build_summary,
    parse_verifier_response,
    run_faithfulness_verification,
)


class FakeLLMClient:
    def __init__(self, contents):
        self.contents = list(contents) if isinstance(contents, list) else [contents]
        self.calls = 0
        self.last_kwargs = {}

    def chat(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        content = self.contents[min(self.calls - 1, len(self.contents) - 1)]
        return type("Response", (), {"content": content, "response_id": f"fake-{self.calls}", "raw": {}})()


def test_build_prompt_with_existing_evidence_id():
    verifier = FaithfulnessVerifier(llm_client=None, model_name="fake")

    system_prompt, user_prompt = verifier.build_prompt(
        candidate=candidate_row(),
        evidence_items=[evidence_row("ev-1")],
        precheck_flags=[],
    )

    assert "strict evidence faithfulness verifier" in system_prompt
    assert "E012_SOA_001" in user_prompt
    assert "ev-1" in user_prompt
    assert "家长反映学校食堂饭菜中出现异物" in user_prompt


def test_missing_evidence_is_marked_without_api(tmp_path):
    fake = FakeLLMClient(supported_payload())

    summary = run_faithfulness_verification(
        candidates=[candidate_row(evidence_ids=["missing"])],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
    )
    rows = read_jsonl(tmp_path / "verified_soa_tuples.jsonl")

    assert fake.calls == 0
    assert summary["num_api_calls"] == 0
    assert rows[0]["verification_label"] == "unsupported"
    assert "missing_evidence" in rows[0]["issue_flags"]


def test_parse_supported_json():
    parsed = parse_verifier_response(supported_payload(), candidate=candidate_row(), model_name="fake")

    assert parsed.parse_success is True
    assert parsed.row["verification_label"] == "supported"
    assert parsed.row["verification_score"] == 0.92


def test_parse_partially_supported_json():
    parsed = parse_verifier_response(
        verifier_payload("partially_supported", 0.55, ["sentiment_not_supported"]),
        candidate=candidate_row(),
        model_name="fake",
    )

    assert parsed.parse_success is True
    assert parsed.row["verification_label"] == "partially_supported"
    assert "sentiment_not_supported" in parsed.row["issue_flags"]


def test_parse_unsupported_json():
    parsed = parse_verifier_response(
        verifier_payload("unsupported", 0.1, ["opinion_overgeneralized"]),
        candidate=candidate_row(),
        model_name="fake",
    )

    assert parsed.parse_success is True
    assert parsed.row["verification_label"] == "unsupported"


def test_markdown_wrapped_json_is_parsed():
    raw = "```json\n" + supported_payload() + "\n```"

    parsed = parse_verifier_response(raw, candidate=candidate_row(), model_name="fake")

    assert parsed.parse_success is True
    assert parsed.row["verification_label"] == "supported"


def test_openai_response_object_is_parsed():
    raw = {"id": "abc", "choices": [{"message": {"content": supported_payload()}}]}

    parsed = parse_verifier_response(raw, candidate=candidate_row(), model_name="fake")

    assert parsed.parse_success is True
    assert parsed.row["verification_label"] == "supported"


def test_empty_response_records_empty_llm_content():
    parsed = parse_verifier_response("", candidate=candidate_row(), model_name="fake")

    assert parsed.parse_success is False
    assert parsed.parse_error == "empty_llm_content"


def test_issue_flags_are_counted():
    summary = build_summary(
        candidates=[candidate_row(), candidate_row(tuple_id="E012_SOA_002")],
        verified=[
            verified_row("supported", ["no_issue"]),
            verified_row("unsupported", ["missing_evidence", "sentiment_not_supported"]),
        ],
        api_calls=1,
        api_failures=0,
        parse_failed_tuples=[],
        missing_evidence_tuples=["E012_SOA_002"],
        output_path="out.jsonl",
        model_name="fake",
    )

    assert summary["issue_flag_distribution"]["missing_evidence"] == 1
    assert summary["issue_flag_distribution"]["sentiment_not_supported"] == 1
    assert summary["supported_rate"] == 0.5


def test_does_not_read_gold_tuples(tmp_path):
    fake = FakeLLMClient(supported_payload())
    gold = tmp_path / "gold_tuples.jsonl"

    run_faithfulness_verification(
        candidates=[candidate_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
    )

    assert fake.calls == 1
    assert not gold.exists()


def test_does_not_generate_gold_tuples(tmp_path):
    fake = FakeLLMClient(supported_payload())

    run_faithfulness_verification(
        candidates=[candidate_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
    )

    assert not (tmp_path / "gold_tuples.jsonl").exists()
    assert not (tmp_path / "gold_event_chains.jsonl").exists()


def test_dry_run_does_not_call_api(tmp_path):
    fake = FakeLLMClient(supported_payload())

    summary = run_faithfulness_verification(
        candidates=[candidate_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=True,
    )

    assert fake.calls == 0
    assert summary["num_api_calls"] == 0
    assert (tmp_path / "verified_soa_tuples.jsonl").exists()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def supported_payload() -> str:
    return verifier_payload("supported", 0.92, ["no_issue"])


def verifier_payload(label: str, score: float, flags: list[str]) -> str:
    return json.dumps(
        {
            "tuple_id": "E012_SOA_001",
            "event_id": "E012",
            "verification_label": label,
            "verification_score": score,
            "verification_rationale": "证据能够支持候选元组。",
            "supported_claims": ["家长反映食堂存在异物"],
            "unsupported_claims": [],
            "evidence_quotes": ["家长反映学校食堂饭菜中出现异物"],
            "issue_flags": flags,
        },
        ensure_ascii=False,
    )


def candidate_row(tuple_id: str = "E012_SOA_001", evidence_ids: list[str] | None = None) -> dict:
    return {
        "event_id": "E012",
        "tuple_id": tuple_id,
        "stakeholder": "家长",
        "opinion": "认为学校食堂存在食品安全问题",
        "sentiment": "negative",
        "rationale": "家长反映饭菜中出现异物",
        "evidence_ids": evidence_ids or ["ev-1"],
        "event_chain_stage": "conflict",
        "confidence": 0.78,
    }


def evidence_row(evidence_id: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "event_id": "E012",
        "source": "news",
        "domain": "example.test",
        "url": f"https://example.test/{evidence_id}",
        "title": "家长质疑学校食堂食品安全",
        "text": "多名家长反映学校食堂饭菜中出现异物，并要求学校说明情况。",
        "quality_score": 0.9,
    }


def chain_row() -> dict:
    return {
        "event_id": "E012",
        "stages": [{"stage": "conflict", "evidence": [{"evidence_id": "ev-1"}]}],
    }


def verified_row(label: str, flags: list[str]) -> dict:
    return {
        "verification_label": label,
        "verification_score": 1.0 if label == "supported" else 0.0,
        "issue_flags": flags,
    }
