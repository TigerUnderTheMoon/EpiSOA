import json

import pytest

from episoa.attribution.schema_attributor import (
    MAX_OPINION_CHARS,
    MAX_RATIONALE_CHARS,
    SchemaAttributor,
    assert_no_total_api_failure,
    build_event_stakeholder_inventory,
    canonicalize_tuple_rows,
    is_pseudo_stakeholder,
    parse_response,
    parse_stage_response,
    run_schema_attribution,
    select_oracle_prompt_evidence,
    select_prompt_evidence,
    stakeholder_candidates_by_event,
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


class FailingLLMClient:
    def __init__(self, message="401 Unauthorized"):
        self.message = message
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        raise RuntimeError(self.message)


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
    assert "stakeholder-canonical" in user_prompt
    assert "There is no fixed per-event tuple target" in user_prompt
    assert "not project/event/media-report titles" in user_prompt
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
    assert '"event_chain_stage": "unknown"' in user_prompt


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


def test_output_over_eight_tuples_is_not_event_capped_and_truncates_long_text():
    rows = []
    for idx in range(10):
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
                "stakeholder_cluster_id": f"stakeholder_{idx:03d}",
                "stakeholder_aliases": [],
                "canonical_tuple": True,
                "opinion_split_reason": "",
                "stakeholder_candidate_match_status": "unmatched",
            }
        )
    raw = json.dumps({"event_id": "E012", "tuples": rows}, ensure_ascii=False)

    parsed = parse_response(raw, event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert len(parsed.tuples) == 10
    assert len(parsed.tuples[0]["opinion"]) <= MAX_OPINION_CHARS
    assert len(parsed.tuples[0]["rationale"]) <= MAX_RATIONALE_CHARS
    assert parsed.tuples[0]["confidence"] == 1.0


def test_parse_response_accepts_mixed_sentiment_and_long_opinion():
    opinion = "This stakeholder supports remediation while raising concerns about compensation timing."
    payload = {
        "event_id": "E012",
        "tuples": [
            {
                **canonical_tuple("Residents", opinion, "stakeholder_001"),
                "sentiment": "mixed",
            }
        ],
    }

    parsed = parse_response(
        json.dumps(payload, ensure_ascii=False),
        event_id="E012",
        allowed_evidence_ids={"ev-1"},
        model_name="fake",
    )

    assert parsed.parse_success is True
    assert parsed.tuples[0]["sentiment"] == "mixed"
    assert len(parsed.tuples[0]["opinion"]) > 40


def test_parse_stage_response_accepts_mixed_sentiment():
    payload = json.loads(stage_payload())
    payload["stage_candidates"][0]["sentiment"] = "mixed"

    parsed = parse_stage_response(
        json.dumps(payload, ensure_ascii=False),
        event_id="E012",
        allowed_evidence_ids={"ev-1"},
        evidence_context_by_id={"ev-1": prompt_evidence("ev-1")},
        model_name="fake",
    )

    assert parsed.parse_success is True
    assert parsed.tuples[0]["sentiment"] == "mixed"


def test_invalid_evidence_id_rejects_tuple_rows():
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
                    "stakeholder_cluster_id": "stakeholder_001",
                    "stakeholder_aliases": [],
                    "canonical_tuple": True,
                    "opinion_split_reason": "",
                    "stakeholder_candidate_match_status": "matched",
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
                    "stakeholder_cluster_id": "stakeholder_002",
                    "stakeholder_aliases": [],
                    "canonical_tuple": True,
                    "opinion_split_reason": "",
                    "stakeholder_candidate_match_status": "matched",
                },
            ],
        },
        ensure_ascii=False,
    )

    parsed = parse_response(raw, event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert len(parsed.tuples) == 0
    assert [row["reason"] for row in parsed.rejected_rows] == ["unknown evidence_id", "unknown evidence_id"]


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
        method_version="legacy",
    )

    assert fake.calls == 2
    assert summary["num_api_calls"] == 2
    assert summary["num_tuples_generated"] == 1


def test_total_api_failure_guard_raises(tmp_path):
    fake = FailingLLMClient()

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

    assert fake.calls == 1
    assert summary["num_api_calls"] == 0
    assert summary["num_api_failures"] == 1
    with pytest.raises(RuntimeError, match="zero successful API calls"):
        assert_no_total_api_failure(summary, tmp_path)


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
    assert summary["attribution_mode"] == "stakeholder_canonical"
    assert summary["stakeholder_candidate_scope"] == "global_fallback"
    assert summary["selection_diagnostics"]["stakeholder_candidate_count"] > 0
    assert summary["canonical_stakeholder_inventory"]


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
        method_version="legacy",
    )

    rows = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = {
        "event_id",
        "tuple_id",
        "stakeholder",
        "stakeholder_cluster_id",
        "stakeholder_aliases",
        "stakeholder_candidate_match_status",
        "matched_stakeholder_candidate",
        "opinion",
        "sentiment",
        "rationale",
        "evidence_ids",
        "canonical_tuple",
        "opinion_split_reason",
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
    assert (tmp_path / "stakeholder_candidate_scope.csv").exists()
    assert (tmp_path / "canonicalization_map.csv").exists()
    assert (tmp_path / "raw_llm_responses.jsonl").exists()
    assert rows[0]["canonical_tuple"] is True


def test_soe_v3_two_pass_writes_stage_candidates_and_final_tuples(tmp_path):
    fake = FakeLLMClient([stage_payload(), merge_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
    )

    candidates = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    stage_rows = [json.loads(line) for line in (tmp_path / "stage_soa_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    raw_rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 2
    assert summary["use_stage_attribution"] is True
    assert summary["num_stage_soa_candidates"] == 1
    assert stage_rows[0]["stage_candidate_id"] == "E012_STAGE_001"
    assert candidates[0]["attribution_pass"] == "soe_v3_two_pass"
    assert candidates[0]["stage_candidate_ids"] == ["E012_STAGE_001"]
    assert candidates[0]["evidence_spans"][0]["text"] == "parents reported"
    assert raw_rows[0]["request_summary"]["attribution_pass"] == "soe_v3_two_pass"


def test_soe_v3_two_pass_falls_back_to_single_pass_after_stage_parse_failure(tmp_path):
    fake = FakeLLMClient(["", "", valid_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
    )

    candidates = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    raw_rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 3
    assert summary["num_api_calls"] == 3
    assert candidates[0]["attribution_pass"] == "legacy_single_pass"
    assert raw_rows[0]["request_summary"]["fallback_mode"] == "legacy_single_pass"


def test_soe_v3_two_pass_falls_back_to_single_pass_after_empty_stage_candidates(tmp_path):
    fake = FakeLLMClient([empty_stage_payload(), valid_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
    )

    candidates = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    raw_rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 2
    assert summary["num_api_calls"] == 2
    assert summary["empty_tuple_events"] == []
    assert candidates[0]["attribution_pass"] == "legacy_single_pass"
    assert raw_rows[0]["request_summary"]["fallback_mode"] == "legacy_single_pass"
    assert raw_rows[0]["request_summary"]["fallback_reason"] == "empty_stage_candidates"
    assert raw_rows[0]["request_summary"]["stage_candidate_count"] == 0


def test_canonical_merge_prompt_requires_cross_stage_stakeholder_merge():
    attributor = SchemaAttributor(llm_client=None, model_name="fake")

    _system_prompt, user_prompt = attributor.build_canonical_merge_prompt(
        event=event_row(),
        evidence_items=[prompt_evidence("ev-1"), prompt_evidence("ev-2")],
        stage_candidates=json.loads(duplicate_stage_payload())["stage_candidates"],
        stakeholder_candidates=["parents"],
    )

    assert "Cross-stage merge guard" in user_prompt
    assert "Do not copy stage-specific candidates into one final tuple per stage" in user_prompt
    assert "opinion_split_reason" in user_prompt


def test_two_pass_merge_deduplicates_same_stakeholder_stage_variants(tmp_path):
    fake = FakeLLMClient([duplicate_stage_payload(), duplicate_merge_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
    )

    candidates = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 2
    assert summary["num_stage_soa_candidates"] == 2
    assert len(candidates) == 1
    assert candidates[0]["stakeholder"] == "parents"
    assert candidates[0]["stage_candidate_ids"] == ["E012_STAGE_001", "E012_STAGE_002"]


def test_two_pass_event_level_safety_net_prefers_event_level_and_supplements_stage(tmp_path):
    fake = FakeLLMClient([stage_payload(), merge_payload(), safety_net_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
        use_event_level_safety_net=True,
    )

    candidates = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    raw_rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 3
    assert summary["num_api_calls"] == 3
    assert len(candidates) == 2
    parents = next(row for row in candidates if row["stakeholder"] == "parents")
    school = next(row for row in candidates if row["stakeholder"] == "school")
    assert parents["opinion"] == "parents report food safety problems"
    assert parents["attribution_pass"] == "soe_v3_event_level_safety_net"
    assert parents["stage_candidate_ids"] == ["E012_STAGE_001"]
    assert school["attribution_pass"] == "soe_v3_event_level_safety_net"
    assert raw_rows[0]["request_summary"]["event_level_safety_net"] is True
    assert raw_rows[0]["request_summary"]["event_level_safety_net_tuple_count"] == 2
    assert raw_rows[0]["request_summary"]["stage_merge_tuple_count"] == 1
    assert raw_rows[0]["request_summary"]["parsed_tuple_count"] == 2


def test_two_pass_event_level_safety_net_is_opt_in(tmp_path):
    fake = FakeLLMClient([stage_payload(), merge_payload(), safety_net_payload()])

    run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
        use_event_level_safety_net=False,
    )

    raw_rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 2
    assert "event_level_safety_net" not in raw_rows[0]["request_summary"]


def test_two_pass_hybrid_refinement_reconciles_stage_and_event_level_outputs(tmp_path):
    fake = FakeLLMClient([stage_payload(), merge_payload(), safety_net_payload(), refined_payload()])

    summary = run_schema_attribution(
        events=[event_row()],
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2")],
        chains=[chain_row()],
        graph_nodes=[],
        llm_client=fake,
        model_name="fake",
        output_dir=tmp_path,
        dry_run=False,
        method_version="soe_v3",
        selector_mode="coverage_optimized",
        use_stage_attribution=True,
        use_event_level_safety_net=True,
        use_hybrid_refinement=True,
    )

    candidates = [json.loads(line) for line in (tmp_path / "candidate_soa_tuples.jsonl").read_text(encoding="utf-8").splitlines()]
    raw_rows = [json.loads(line) for line in (tmp_path / "raw_llm_responses.jsonl").read_text(encoding="utf-8").splitlines()]

    assert fake.calls == 4
    assert summary["num_api_calls"] == 4
    assert len(candidates) == 1
    assert candidates[0]["stakeholder"] == "parents"
    assert candidates[0]["opinion"] == "parents request a cafeteria safety explanation"
    assert candidates[0]["attribution_pass"] == "soe_v3_hybrid_refinement"
    assert raw_rows[0]["request_summary"]["hybrid_refinement"] is True
    assert raw_rows[0]["request_summary"]["hybrid_refinement_tuple_count"] == 1
    assert "hybrid_refinement" in json.loads(raw_rows[0]["raw_response"])


def test_parse_stage_response_accepts_stage_candidates():
    parsed = parse_stage_response(
        stage_payload(),
        event_id="E012",
        allowed_evidence_ids={"ev-1"},
        evidence_context_by_id={"ev-1": prompt_evidence("ev-1")},
        model_name="fake",
    )

    assert parsed.parse_success is True
    assert parsed.tuples[0]["stage_candidate_id"] == "E012_STAGE_001"
    assert parsed.tuples[0]["evidence_spans"][0]["evidence_id"] == "ev-1"


def test_duplicate_cluster_without_split_reason_is_rejected():
    payload = {
        "event_id": "E012",
        "tuples": [
            canonical_tuple("家长", "认为存在问题", "stakeholder_001"),
            canonical_tuple("家长", "要求说明情况", "stakeholder_001"),
        ],
    }

    parsed = parse_response(json.dumps(payload, ensure_ascii=False), event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert len(parsed.tuples) == 1
    assert parsed.rejected_rows[0]["reason"] == "duplicate stakeholder_cluster_id without opinion_split_reason"


def test_duplicate_cluster_with_split_reason_is_allowed():
    payload = {
        "event_id": "E012",
        "tuples": [
            canonical_tuple("家长", "认为存在问题", "stakeholder_001"),
            canonical_tuple("家长", "要求说明情况", "stakeholder_001", split_reason="不同诉求"),
        ],
    }

    parsed = parse_response(json.dumps(payload, ensure_ascii=False), event_id="E012", allowed_evidence_ids={"ev-1"}, model_name="fake")

    assert len(parsed.tuples) == 2


def test_candidate_outside_graph_is_kept_as_unmatched():
    payload = {"event_id": "E012", "tuples": [canonical_tuple("校外商户", "否认供餐问题", "stakeholder_009")]}

    parsed = parse_response(
        json.dumps(payload, ensure_ascii=False),
        event_id="E012",
        allowed_evidence_ids={"ev-1"},
        allowed_stakeholders=["家长", "学校"],
        model_name="fake",
    )

    assert len(parsed.tuples) == 1
    assert parsed.tuples[0]["stakeholder_candidate_match_status"] == "unmatched"


def test_stakeholder_candidates_are_event_scoped_not_global():
    nodes = [
        {
            "node_type": "stakeholder_candidate",
            "node_id": "stakeholder:E1:agency",
            "attributes": {"stakeholder": "Agency A", "event_id": "E1"},
        },
        {
            "node_type": "stakeholder_candidate",
            "node_id": "stakeholder:E2:residents",
            "attributes": {"stakeholder": "Residents B", "event_id": "E2"},
        },
    ]

    by_event = stakeholder_candidates_by_event(nodes)

    assert by_event["E1"] == ["Agency A"]
    assert by_event["E2"] == ["Residents B"]
    assert set(by_event["__global__"]) == {"Agency A", "Residents B"}


def test_event_inventory_filters_project_and_generic_stakeholders():
    event = {"event_id": "E1", "event_name": "三元里村城中村改造项目", "stakeholder_hints": ["三元里村党委及村集体"]}

    inventory = build_event_stakeholder_inventory(
        event,
        ["三元里村城中村改造项目", "政府部门", "三元里村党委及村集体"],
        [{"title": "三元里村党委书记回应旧改", "text": "三元里村党委书记韦联建表示支持改造。"}],
    )

    assert "三元里村党委及村集体" in inventory
    assert "三元里村城中村改造项目" not in inventory
    assert "政府部门" not in inventory
    assert is_pseudo_stakeholder("三元里村城中村改造项目", event) is True


def test_post_extraction_canonicalizer_remaps_alias_and_drops_pseudo():
    event = {"event_id": "E1", "event_name": "三元里村城中村改造项目", "stakeholder_hints": ["三元里村党委及村集体"]}
    rows = [
        {
            **canonical_tuple("三元里村党委书记韦联建", "支持旧改并认为可提升集体收益", "stakeholder_001"),
            "event_id": "E1",
            "tuple_id": "E1_SOA_001",
            "stakeholder_id": "old",
            "opinion_id": "old",
        },
        {
            **canonical_tuple("三元里村城中村改造项目", "不存在资金链断裂风险", "stakeholder_002"),
            "event_id": "E1",
            "tuple_id": "E1_SOA_002",
            "stakeholder_id": "old",
            "opinion_id": "old",
        },
    ]

    canonical_rows, diagnostics = canonicalize_tuple_rows(
        rows,
        event=event,
        stakeholder_candidates=["三元里村党委及村集体"],
        evidence_items=[],
    )

    assert [row["stakeholder"] for row in canonical_rows] == ["三元里村党委及村集体"]
    assert diagnostics["dropped_pseudo_stakeholder_count"] == 1
    assert diagnostics["remapped_stakeholder_count"] == 1


def test_select_prompt_evidence_prefers_chain_context():
    selected = select_prompt_evidence(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2")],
        max_evidence=1,
    )

    assert selected[0]["evidence_id"] == "ev-1"
    assert selected[0]["stage"] == "conflict"


def test_select_oracle_prompt_evidence_keeps_gold_ids_first():
    selected = select_oracle_prompt_evidence(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[evidence_row("ev-1"), evidence_row("ev-2"), evidence_row("ev-3")],
        oracle_evidence_ids=["ev-2"],
        max_evidence=2,
    )

    assert [row["evidence_id"] for row in selected] == ["ev-2", "ev-1"]


def valid_payload() -> str:
    return json.dumps(
        {
            "event_id": "E012",
            "tuples": [
                canonical_tuple("家长", "认为学校食堂存在食品安全问题", "stakeholder_001")
            ],
        },
        ensure_ascii=False,
    )


def stage_payload() -> str:
    return json.dumps(
        {
            "event_id": "E012",
            "stage_candidates": [
                {
                    "stage_candidate_id": "E012_STAGE_001",
                    "stakeholder": "parents",
                    "opinion": "report food safety concerns",
                    "sentiment": "negative",
                    "event_chain_stage": "conflict",
                    "rationale": "parents reported foreign objects in meals",
                    "evidence_ids": ["ev-1"],
                    "evidence_spans": [{"evidence_id": "ev-1", "char_start": 0, "char_end": 12, "text": "parents reported"}],
                    "confidence": 0.8,
                }
            ],
        },
        ensure_ascii=False,
    )


def empty_stage_payload() -> str:
    return json.dumps({"event_id": "E012", "stage_candidates": []}, ensure_ascii=False)


def duplicate_stage_payload() -> str:
    return json.dumps(
        {
            "event_id": "E012",
            "stage_candidates": [
                {
                    "stage_candidate_id": "E012_STAGE_001",
                    "stakeholder": "parents",
                    "opinion": "report food safety concerns",
                    "sentiment": "negative",
                    "event_chain_stage": "conflict",
                    "rationale": "parents reported foreign objects in meals",
                    "evidence_ids": ["ev-1"],
                    "evidence_spans": [{"evidence_id": "ev-1", "char_start": 0, "char_end": 12, "text": "parents reported"}],
                    "confidence": 0.8,
                },
                {
                    "stage_candidate_id": "E012_STAGE_002",
                    "stakeholder": "parents",
                    "opinion": "report food safety concerns",
                    "sentiment": "negative",
                    "event_chain_stage": "response",
                    "rationale": "parents requested school explanation",
                    "evidence_ids": ["ev-2"],
                    "evidence_spans": [{"evidence_id": "ev-2", "char_start": 0, "char_end": 12, "text": "parents requested"}],
                    "confidence": 0.78,
                },
            ],
        },
        ensure_ascii=False,
    )


def merge_payload() -> str:
    payload = json.loads(valid_payload())
    payload["tuples"][0]["stage_candidate_ids"] = ["E012_STAGE_001"]
    return json.dumps(payload, ensure_ascii=False)


def duplicate_merge_payload() -> str:
    first = canonical_tuple(
        "parents",
        "report food safety concerns",
        "stakeholder_001",
        evidence_ids=["ev-1"],
    )
    second = canonical_tuple(
        "parents",
        "report food safety concerns",
        "stakeholder_002",
        evidence_ids=["ev-2"],
    )
    first["stage_candidate_ids"] = ["E012_STAGE_001"]
    second["stage_candidate_ids"] = ["E012_STAGE_002"]
    return json.dumps({"event_id": "E012", "tuples": [first, second]}, ensure_ascii=False)


def safety_net_payload() -> str:
    parents = canonical_tuple(
        "parents",
        "parents report food safety problems",
        "stakeholder_001",
        evidence_ids=["ev-1"],
    )
    school = canonical_tuple(
        "school",
        "school says it will inspect the cafeteria and explain the situation",
        "stakeholder_002",
        evidence_ids=["ev-2"],
    )
    return json.dumps({"event_id": "E012", "tuples": [parents, school]}, ensure_ascii=False)


def refined_payload() -> str:
    parents = canonical_tuple(
        "parents",
        "parents request a cafeteria safety explanation",
        "stakeholder_001",
        evidence_ids=["ev-1"],
    )
    parents["stage_candidate_ids"] = ["E012_STAGE_001"]
    return json.dumps({"event_id": "E012", "tuples": [parents]}, ensure_ascii=False)


def canonical_tuple(
    stakeholder: str,
    opinion: str,
    cluster_id: str,
    *,
    split_reason: str = "",
    evidence_ids: list[str] | None = None,
) -> dict:
    return {
        "stakeholder": stakeholder,
        "opinion": opinion,
        "sentiment": "negative",
        "rationale": "家长反映饭菜中出现异物",
        "evidence_ids": evidence_ids or ["ev-1"],
        "event_chain_stage": "conflict",
        "support_status": "candidate_supported",
        "confidence": 0.78,
        "stakeholder_cluster_id": cluster_id,
        "stakeholder_aliases": [stakeholder],
        "canonical_tuple": True,
        "opinion_split_reason": split_reason,
        "stakeholder_candidate_match_status": "matched",
    }


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
