import json

from episoa.attribution.schema_attributor import (
    MAX_OPINION_CHARS,
    MAX_RATIONALE_CHARS,
    SchemaAttributor,
    parse_response,
    run_schema_attribution,
    select_prompt_evidence,
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


def test_prompt_contains_event_and_evidence_id():
    attributor = SchemaAttributor(llm_client=None, model_name="fake")
    system_prompt, user_prompt = attributor.build_prompt(
        event=event_row(),
        chain=chain_row(),
        evidence_items=[prompt_evidence("ev-1")],
        stakeholder_candidates=["家长"],
    )

    assert "E012" in user_prompt
    assert "学校食堂食品安全争议" in user_prompt
    assert "ev-1" in user_prompt
    assert "最多输出 4 条" in user_prompt
    assert "Return strict JSON only" in system_prompt


def test_hidden_chain_prompt_omits_chain_fields():
    attributor = SchemaAttributor(llm_client=None, model_name="fake")
    _system_prompt, user_prompt = attributor.build_prompt(
        event=event_row(),
        chain=chain_row(),
        evidence_items=[prompt_evidence("ev-1")],
        stakeholder_candidates=["Residents"],
        hide_chain_in_prompt=True,
    )

    assert "chain_confidence" not in user_prompt
    assert "missing_stages" not in user_prompt
    assert "stage:" not in user_prompt
    assert "final_stage_score" not in user_prompt
    assert "event_relevance_score" not in user_prompt
    assert "event_chain_stage" not in user_prompt


def test_parse_response_accepts_pure_json():
    parsed = parse_response(valid_payload(), event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is True
    assert len(parsed.tuples) == 1
    assert parsed.tuples[0]["tuple_id"] == "E012_SOA_001"


def test_parse_response_accepts_markdown_json():
    raw = "```json\n" + valid_payload() + "\n```"

    parsed = parse_response(raw, event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is True
    assert len(parsed.tuples) == 1


def test_parse_response_accepts_openai_response_object():
    raw = {"id": "abc", "choices": [{"message": {"content": valid_payload()}}]}

    parsed = parse_response(raw, event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is True
    assert len(parsed.tuples) == 1


def test_empty_content_returns_empty_llm_content():
    parsed = parse_response("", event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is False
    assert parsed.parse_error == "empty_llm_content"


def test_malformed_json_returns_incomplete_or_malformed_json():
    parsed = parse_response('{"event_id":"E012","tuples":[', event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is False
    assert parsed.parse_error == "incomplete_or_malformed_json"


def test_no_json_object_is_reported():
    parsed = parse_response("no json here", event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is False
    assert parsed.parse_error == "no JSON object found"


def test_output_over_four_tuples_keeps_first_four_and_truncates_long_text():
    rows = []
    for idx in range(6):
        rows.append(
            {
                "stakeholder": f"主体{idx}",
                "opinion": "很长的观点" * 20,
                "sentiment": "negative",
                "rationale": "很长的依据" * 30,
                "evidence_ids": ["ev-1"],
                "event_chain_stage": "conflict",
                "support_status": "candidate_supported",
                "confidence": 1.5,
            }
        )
    raw = json.dumps({"event_id": "E012", "tuples": rows}, ensure_ascii=False)

    parsed = parse_response(raw, event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert len(parsed.tuples) == 4
    assert len(parsed.tuples[0]["opinion"]) <= MAX_OPINION_CHARS
    assert len(parsed.tuples[0]["rationale"]) <= MAX_RATIONALE_CHARS
    assert parsed.tuples[0]["confidence"] == 1.0


def test_invalid_evidence_id_is_filtered_and_empty_tuple_dropped():
    raw = json.dumps(
        {
            "event_id": "E012",
            "tuples": [
                {
                    "stakeholder": "家长",
                    "opinion": "认为存在问题",
                    "sentiment": "negative",
                    "rationale": "来自证据",
                    "evidence_ids": ["missing"],
                    "event_chain_stage": "conflict",
                    "support_status": "candidate_supported",
                    "confidence": 0.5,
                },
                {
                    "stakeholder": "家长",
                    "opinion": "要求学校说明",
                    "sentiment": "negative",
                    "rationale": "来自证据",
                    "evidence_ids": ["missing", "ev-1"],
                    "event_chain_stage": "conflict",
                    "support_status": "candidate_supported",
                    "confidence": 0.5,
                },
            ],
        },
        ensure_ascii=False,
    )

    parsed = parse_response(raw, event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert len(parsed.tuples) == 1
    assert parsed.tuples[0]["evidence_ids"] == ["ev-1"]


def test_parse_response_rejects_invalid_sentiment():
    payload = json.loads(valid_payload())
    payload["tuples"][0]["sentiment"] = "angry"

    parsed = parse_response(json.dumps(payload, ensure_ascii=False), event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is True
    assert parsed.tuples == []


def test_empty_tuples_are_valid():
    parsed = parse_response('{"event_id":"E012","tuples":[]}', event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert parsed.parse_success is True
    assert parsed.tuples == []


def test_dry_run_does_not_call_llm(tmp_path):
    fake = FakeLLMClient('{"event_id":"E012","tuples":[]}')
    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=True,
    )

    assert fake.calls == 0
    assert summary["num_api_calls"] == 0


def test_empty_llm_content_retries_with_short_prompt(tmp_path):
    fake = FakeLLMClient(["", valid_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
    )

    assert fake.calls == 2
    assert summary["num_api_calls"] == 2
    assert summary["num_tuples_generated"] == 1


def test_raw_response_records_ablation_request_summary_flags(tmp_path):
    fake = FakeLLMClient(valid_payload())

    run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        hide_chain_in_prompt=True,
        skip_chain_ranking=True,
    )

    rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = rows[0]["request_summary"]

    assert summary["selected_evidence_ids"] == ["ev-1"]
    assert summary["prompt_chars"] > 0
    assert summary["chain_confidence"] == 0
    assert summary["hide_chain_in_prompt"] is True
    assert summary["skip_chain_ranking"] is True


def test_module_does_not_read_or_generate_gold(tmp_path):
    gold = tmp_path / "gold_tuples.jsonl"
    fake = FakeLLMClient('{"event_id":"E012","tuples":[]}')

    run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
    )

    assert not gold.exists()


def test_output_candidate_tuple_fields_are_complete(tmp_path):
    fake = FakeLLMClient(valid_payload())

    run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
    )

    rows = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = {
        "event_id",
        "tuple_id",
        "stakeholder",
        "opinion",
        "sentiment",
        "rationale",
        "evidence_ids",
        "event_chain_stage",
        "support_status",
        "confidence",
        "model_name",
        "prompt_version",
        "raw_response_id",
        "created_at",
    }

    assert expected <= set(rows[0])
    assert (tmp_path / "schema_attribution_summary.json").exists()
    assert (tmp_path / "schema_attribution_table.csv").exists()
    assert (tmp_path / "raw_llm_responses.jsonl").exists()


def test_select_prompt_evidence_prefers_chain_context():
    selected = select_prompt_evidence(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2")],
        max_evidence=1,
    )

    assert selected[0]["evidence_id"] == "ev-1"
    assert selected[0]["stage"] == "conflict"


def valid_payload() -> str:
    return json.dumps(
        {
            "event_id": "E012",
            "tuples": [
                {
                    "stakeholder": "家长",
                    "opinion": "认为学校食堂存在食品安全问题",
                    "sentiment": "negative",
                    "rationale": "家长反映饭菜中出现异物",
                    "evidence_ids": ["ev-1"],
                    "event_chain_stage": "conflict",
                    "support_status": "candidate_supported",
                    "confidence": 0.78,
                }
            ],
        },
        ensure_ascii=False,
    )


def event_row() -> dict:
    return {
        "event_id": "E012",
        "event_name": "学校食堂食品安全争议",
        "event_description": "围绕学校食堂饭菜质量和家长质疑形成的公共事件。",
        "seed_keywords": ["学校食堂 食品安全", "家长 质疑"],
        "stakeholder_hints": ["家长", "学校", "监管部门"],
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


def prompt_evidence(evidence_id: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "stage": "conflict",
        "source": "news",
        "domain": "example.test",
        "url": f"https://example.test/{evidence_id}",
        "title": "家长质疑学校食堂食品安全",
        "text_excerpt": "多名家长反映学校食堂饭菜中出现异物。",
        "final_stage_score": 0.8,
        "event_relevance_score": 0.9,
    }


def chain_row() -> dict:
    return {
        "event_id": "E012",
        "chain_confidence": 0.7,
        "missing_stages": [],
        "stages": [
            {
                "stage": "conflict",
                "stage_order": 3,
                "evidence": [
                    {
                        "evidence_id": "ev-1",
                        "final_stage_score": 0.8,
                        "event_relevance_score": 0.9,
                        "source": "news",
                        "domain": "example.test",
                        "url": "https://example.test/ev-1",
                        "title": "家长质疑学校食堂食品安全",
                        "text_excerpt": "多名家长反映学校食堂饭菜中出现异物。",
                    }
                ],
            }
        ],
    }
