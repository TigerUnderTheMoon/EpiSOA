from argparse import Namespace
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "collect_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_evidence_script", SCRIPT_PATH)
collect_evidence_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collect_evidence_script)
collect_from_cli = collect_evidence_script.collect_from_cli
evaluate_coverage = collect_evidence_script.evaluate_coverage
plan_event_queries = collect_evidence_script.plan_event_queries


def test_collect_evidence_planned_only_when_search_api_missing(tmp_path):
    events = tmp_path / "events.jsonl"
    config = tmp_path / "collector.yaml"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"

    events.write_text(
        '{"event_id":"e1","event_name":"Transit plan vote",'
        '"event_description":"A concrete transit plan vote in Test City",'
        '"location":{"city":"Test City"},"time_window":{"start":"2025-01-01","end":"2025-01-02"},'
        '"trigger":"city council vote","anchor_entities":{"government":"Test City Council"},'
        '"anchor_urls":["https://source.test/event"],"query_seeds":["transit plan"],'
        '"source_scope":["news"],"domain":"urban_mobility","event_type":"concrete_event",'
        '"stakeholder_hints":["residents"],"stance_hints":["concern"],'
        '"temporal_stages":["trigger","conflict","response"]}\n',
        encoding="utf-8",
    )
    config.write_text(
        """
search:
  provider: custom
  api_key: ""
  api_key_env: SEARCH_API_KEY
  base_url: ""
  base_url_env: SEARCH_BASE_URL
collector:
  max_results_per_query: 2
  max_evidence_per_event: 3
  sleep_seconds: 0
""",
        encoding="utf-8",
    )

    code = collect_from_cli(
        Namespace(
            events=str(events),
            config=str(config),
            output=str(output),
            query_plan_output=str(query_plan),
            coverage_output=str(coverage),
            recollection=False,
            resume=False,
            max_events=None,
            max_queries_per_event=6,
            debug_output=str(tmp_path / "debug.json"),
            planner_debug_output=str(tmp_path / "planner_debug.json"),
        )
    )

    assert code == 0
    assert output.read_text(encoding="utf-8") == ""
    plan = [json.loads(line) for line in query_plan.read_text(encoding="utf-8").splitlines()]
    report = json.load(coverage.open("r", encoding="utf-8"))
    assert plan[0]["planned_only"] is True
    assert plan[0]["expanded_keywords"]
    assert report["planned_only"] is True
    assert "collection_skipped_reason" in report


def test_social_media_source_scope_is_normalized_to_public_social():
    event = {
        "event_id": "e1",
        "event_name": "Transit plan",
        "seed_keywords": ["transit plan"],
        "source_scope": ["news", "social_media"],
    }

    plan = plan_event_queries(event)
    coverage = evaluate_coverage(event, [{"source": "public_social", "url": "https://example.test", "text": "post"}])

    planned_sources = {item["source_type"] for item in plan["query_rounds"]}
    assert {"news", "public_social"} <= planned_sources
    assert all(item["source_scope"] == [item["source_type"]] for item in plan["query_rounds"])
    assert "social_media" not in coverage["source_coverage"]
    assert "public_social" in coverage["source_coverage"]
    assert coverage["temporal_stage_coverage_mode"] == "rule_based_chinese_semantic"


def test_unsupported_initial_planner_mode_falls_back_to_heuristic():
    event = {
        "event_id": "e1",
        "event_name": "Transit plan",
        "seed_keywords": ["transit plan"],
        "source_scope": ["news"],
    }

    plans, debug = collect_evidence_script.build_initial_query_plans(
        events=[event],
        planner_mode="g" + "a",
        default_sources=["news"],
    )

    assert plans[0]["query_rounds"]
    assert plans[0]["query_rounds"][0]["query"] == "transit plan"
    assert debug["effective_mode"] == "heuristic"
    assert debug["fallback_reason"] == "unsupported_planner_mode"
    assert debug["events"][0]["fallback_reason"] == "unsupported_planner_mode"


def test_initial_collection_respects_max_queries_per_event():
    client = CountingClient()
    event = {"event_id": "e1", "time_window": {"start": "2025-01-01", "end": "2025-01-02"}}
    plan = {
        "query_rounds": [
            {"round": 1, "query": "first", "source_scope": ["news"]},
            {"round": 2, "query": "second", "source_scope": ["news"]},
        ]
    }

    posts = collect_evidence_script._collect_for_plan(
        client,
        event,
        plan,
        max_results_per_query=1,
        max_evidence_per_event=10,
        max_queries_per_event=1,
        sleep_seconds=0,
        errors=[],
    )

    assert [call["query"] for call in client.calls] == ["first"]
    assert len(posts) == 1


def test_initial_plan_generates_multiple_source_type_queries():
    event = {
        "event_id": "e1",
        "event_name": "Transit plan",
        "query_seeds": ["transit plan"],
        "source_scope": ["official", "news", "public_interaction", "forum", "public_social"],
    }

    plan = plan_event_queries(event)
    planned_sources = {item["source_type"] for item in plan["query_rounds"]}

    assert {"official", "news", "public_interaction", "forum", "public_social"} <= planned_sources
    assert planned_sources != {"news"}
    assert all(item["source_scope"] == [item["source_type"]] for item in plan["query_rounds"])


def test_official_queries_are_site_scoped_and_budgeted():
    event = {
        "event_id": "e1",
        "event_name": "深圳市罗湖区金钻豪园旧改过渡安置费拖欠事件",
        "query_seeds": ["金钻豪园 过渡安置费 拖欠"],
        "location": {"city": "深圳市", "district": "罗湖区"},
        "source_scope": ["official", "news"],
    }

    plan = plan_event_queries(event)
    official_rounds = [item for item in plan["query_rounds"] if item["source_type"] == "official"]

    assert 1 <= len(official_rounds) <= 4
    assert any("site:szlh.gov.cn" in item["query"] for item in official_rounds)
    assert any("site:gov.cn" in item["query"] for item in official_rounds)
    assert any(any(keyword in item["query"] for keyword in ["公示", "公告", "批复", "信息公开", "政务公开"]) for item in official_rounds)


def test_repair_rounds_are_targeted_by_gap_type():
    event = {
        "event_id": "e1",
        "event_name": "Transit plan",
        "query_seeds": ["transit plan"],
        "source_scope": ["official", "news", "forum"],
    }
    source_gap_coverage = {
        "missing_sources": ["official"],
        "missing_stakeholders": ["residents"],
        "missing_stances": ["concern"],
        "missing_temporal_stages": ["response"],
    }

    source_rounds = collect_evidence_script.build_repair_rounds(event, source_gap_coverage, 1)

    assert any(item["source_type"] == "official" and item["reason"] == "missing_official" for item in source_rounds)
    semantic_gap_coverage = {
        "missing_sources": [],
        "missing_stakeholders": ["residents"],
        "missing_stances": ["concern"],
        "missing_temporal_stages": ["response"],
    }
    rounds = collect_evidence_script.build_repair_rounds(event, semantic_gap_coverage, 1)
    assert any(item["target_stakeholder"] == "residents" for item in rounds)
    assert any(item["target_stance"] for item in rounds)
    assert any(item["target_temporal_stage"] for item in rounds)
    assert all(item["reason"] in {"missing stakeholder: residents", "missing stance", "missing temporal stage"} for item in rounds)


def test_repair_rounds_generate_gap_specific_budgeted_queries():
    event = {"event_id": "e1", "event_name": "Transit plan", "query_seeds": ["transit plan"], "source_scope": ["news", "public_interaction"]}

    stance_rounds = collect_evidence_script.build_repair_rounds(
        event,
        {"missing_sources": [], "missing_stakeholders": [], "missing_stances": ["minimum_non_neutral_stances"], "missing_temporal_stages": []},
        1,
    )
    temporal_rounds = collect_evidence_script.build_repair_rounds(
        event,
        {"missing_sources": [], "missing_stakeholders": [], "missing_stances": [], "missing_temporal_stages": ["minimum_temporal_stages"]},
        1,
    )
    low_raw_rounds = collect_evidence_script.build_repair_rounds(
        event,
        {"missing_sources": [], "missing_stakeholders": [], "missing_stances": [], "missing_temporal_stages": [], "missing_raw_count": 1},
        1,
    )

    assert 1 <= len(stance_rounds) <= 6
    assert all(item["reason"] == "missing stance" and item["target_stance"] for item in stance_rounds)
    assert 1 <= len(temporal_rounds) <= 7
    assert all(item["reason"] == "missing temporal stage" and item["target_temporal_stage"] for item in temporal_rounds)
    assert 1 <= len(low_raw_rounds) <= 6
    assert all(item["reason"] == "raw count below minimum" for item in low_raw_rounds)
    assert {item["source_type"] for item in low_raw_rounds} <= {"news", "official", "public_interaction"}


def test_missing_official_repair_queries_are_official_specific_and_budgeted():
    event = {
        "event_id": "e1",
        "event_name": "深圳市罗湖区金钻豪园旧改过渡安置费拖欠事件",
        "query_seeds": ["金钻豪园 过渡安置费 拖欠"],
        "location": {"city": "深圳市", "district": "罗湖区"},
        "source_scope": ["official", "news"],
    }
    coverage = {"missing_sources": ["official"], "missing_stakeholders": [], "missing_stances": [], "missing_temporal_stages": []}

    rounds = collect_evidence_script.build_repair_rounds(event, coverage, 1)

    assert 1 <= len(rounds) <= 8
    assert {item["source_type"] for item in rounds} == {"official"}
    assert all(item["reason"] == "missing_official" for item in rounds)
    assert any("site:gov.cn" in item["query"] for item in rounds)
    assert any(any(keyword in item["query"] for keyword in ["政务公开", "信息公开", "批复", "回应", "通报"]) for item in rounds)


def test_collection_preserves_source_type_and_records_empty_attempts():
    client = SelectiveClient()
    event = {"event_id": "e1", "time_window": {"start": "2025-01-01", "end": "2025-01-02"}}
    plan = {
        "query_rounds": [
            {"round": 1, "query": "official q", "source_type": "official", "source_scope": ["official"]},
            {"round": 1, "query": "forum q", "source_type": "forum", "source_scope": ["forum"]},
        ]
    }
    attempts = []

    posts = collect_evidence_script._collect_for_plan(
        client,
        event,
        plan,
        max_results_per_query=2,
        max_evidence_per_event=4,
        max_queries_per_event=2,
        sleep_seconds=0,
        errors=[],
        attempts=attempts,
    )

    assert posts[0]["source"] == "official"
    assert posts[0]["source_type"] == "official"
    assert posts[0]["requested_source_type"] == "official"
    assert posts[0]["detected_source_type"] == "official"
    assert any(item["source_type"] == "forum" and item["empty_source_attempt"] for item in attempts)


def test_official_collection_reranks_detected_official_before_news():
    client = MixedOfficialClient()
    event = {"event_id": "e1", "time_window": {"start": "2025-01-01", "end": "2025-01-02"}}
    plan = {"query_rounds": [{"round": 1, "query": "official q", "source_type": "official", "source_scope": ["official"]}]}
    attempts = []

    posts = collect_evidence_script._collect_for_plan(
        client,
        event,
        plan,
        max_results_per_query=2,
        max_evidence_per_event=1,
        max_queries_per_event=1,
        sleep_seconds=0,
        errors=[],
        attempts=attempts,
    )

    assert len(posts) == 1
    assert posts[0]["detected_source_type"] == "official"
    assert "gov.cn" in posts[0]["url"]
    assert attempts[0]["detected_official_count"] == 1


def test_dedupe_preserves_source_type_for_kept_rows():
    posts = [
        {"raw_id": "r1", "event_id": "E001", "source": "official", "source_type": "official", "url": "https://example.test/a", "text": "a"},
        {"raw_id": "r2", "event_id": "E001", "source": "news", "source_type": "news", "url": "https://example.test/b", "text": "a"},
    ]

    deduped = collect_evidence_script._dedupe_posts(posts)

    assert len(deduped) == 2
    assert {item["source_type"] for item in deduped} == {"official", "news"}


def test_dedupe_drops_duplicate_event_normalized_url_pairs():
    posts = [
        {"raw_id": "r1", "event_id": "E001", "source_type": "news", "url": "https://example.test/a?utm_source=x&keep=1#frag", "text": "a"},
        {"raw_id": "r2", "event_id": "E001", "source_type": "official", "url": "https://example.test/a?keep=1&spm=abc", "text": "b"},
        {"raw_id": "r3", "event_id": "E002", "source_type": "news", "url": "https://example.test/a?keep=1", "text": "c"},
    ]

    deduped = collect_evidence_script._dedupe_posts(posts)

    assert [item["raw_id"] for item in deduped] == ["r1", "r3"]
    assert collect_evidence_script.normalize_event_url("https://example.test/a?utm_source=x&keep=1#frag") == "https://example.test/a?keep=1"


def test_coverage_report_status_distinguishes_provider_warnings():
    event = _formal_event("E001", "first")
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"居民投诉质疑，部门回应整改完成后续追踪 {i}",
            "text": f"居民投诉质疑，部门回应整改完成后续追踪，专家支持 {i}。",
        }
        for i in range(15)
    ]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [{"event_id": "E001", "query": "q", "source_type": "news", "error_type": "ConnectTimeout"}],
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "passed_with_provider_warnings"
    assert report["provider_errors"]
    assert report["events_need_recollection"] == []


def test_coverage_report_fails_gate_even_without_provider_errors():
    event = _formal_event("E001", "first")

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": []},
        [],
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "failed"
    assert report["missing_events"] == ["E001"]
    assert report["events_need_recollection"]


def test_coverage_report_passed_without_provider_errors():
    event = _formal_event("E001", "first")
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"居民投诉质疑，部门回应整改完成后续追踪 {i}",
            "text": f"居民投诉质疑，部门回应整改完成后续追踪，专家支持 {i}。",
        }
        for i in range(15)
    ]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "passed"
    assert report["provider_errors"] == []
    assert report["events_need_recollection"] == []
    assert report["duplicate_raw_id_count"] == 0
    assert report["duplicate_event_url_pair_count"] == 0


def test_coverage_report_failed_with_provider_errors_when_data_gate_fails():
    event = _formal_event("E001", "first")

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": []},
        [{"event_id": "E001", "query": "q", "source_type": "news", "error_type": "ConnectTimeout"}],
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "failed"
    assert report["provider_errors"]
    assert report["missing_events"] == ["E001"]


def test_coverage_report_failed_on_duplicate_event_url_pairs():
    event = _formal_event("E001", "first")
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": "https://people.com.cn/same-article",
            "title": f"居民投诉质疑 {i}",
            "text": f"居民投诉质疑，部门回应整改完成后续追踪 {i}。",
        }
        for i in range(15)
    ]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "failed"
    assert report["duplicate_event_url_pair_count"] > 0
    assert report["duplicate_event_url_pairs"]


def test_coverage_report_failed_on_duplicate_raw_ids():
    event = _formal_event("E001", "first")
    posts = []
    for i in range(15):
        posts.append({
            "raw_id": "dup_id",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"title {i}",
            "text": f"text {i}",
        })

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "failed"
    assert report["duplicate_raw_id_count"] > 0


def test_coverage_report_failed_on_official_missing():
    event = _formal_event("E001", "first")
    event["source_scope"] = ["official", "news"]
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"title {i}",
            "text": f"text {i}",
        }
        for i in range(15)
    ]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["official", "news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "failed"
    assert "E001" in report["official_missing_events"]


def test_coverage_report_failed_on_interaction_missing():
    event = _formal_event("E001", "first")
    event["source_scope"] = ["official", "news", "forum"]
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "official",
            "source_type": "official",
            "url": f"https://gov.cn/a{i}",
            "title": f"title {i}",
            "text": f"text {i}",
        }
        for i in range(15)
    ]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["official", "news", "forum"],
        min_raw_per_event=15,
    )

    assert report["status"] == "failed"
    assert "E001" in report["interaction_missing_events"]


def test_coverage_report_failed_on_duplicate_query_plan_event_ids():
    event = _formal_event("E001", "first")
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"title {i}",
            "text": f"text {i}",
        }
        for i in range(15)
    ]
    query_plans = [{"event_id": "E001"}, {"event_id": "E001"}]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["news"],
        min_raw_per_event=15,
        query_plans=query_plans,
    )

    assert report["status"] == "failed"
    assert report["duplicate_query_plan_event_id_count"] > 0


def test_coverage_report_includes_provider_warnings_field():
    event = _formal_event("E001", "first")
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"居民投诉质疑，部门回应整改完成后续追踪 {i}",
            "text": f"居民投诉质疑，部门回应整改完成后续追踪，专家支持 {i}。",
        }
        for i in range(15)
    ]
    provider_errors = [{"event_id": "E001", "query": "q", "source_type": "news", "error_type": "ConnectTimeout"}]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        provider_errors,
        default_sources=["news"],
        min_raw_per_event=15,
    )

    assert report["status"] == "passed_with_provider_warnings"
    assert report["provider_errors"] == provider_errors
    assert report["provider_warnings"] == provider_errors
    assert report["errors"] == provider_errors


def test_coverage_report_new_fields_present():
    event = _formal_event("E001", "first")
    posts = [
        {
            "raw_id": f"r{i}",
            "event_id": "E001",
            "source": "news",
            "source_type": "news",
            "url": f"https://people.com.cn/a{i}",
            "title": f"title {i}",
            "text": f"text {i}",
        }
        for i in range(15)
    ]

    report = collect_evidence_script.build_coverage_report(
        [event],
        {"E001": posts},
        [],
        default_sources=["news"],
        min_raw_per_event=15,
        query_plans=[{"event_id": "E001"}],
    )

    assert report["duplicate_raw_id_count"] == 0
    assert report["duplicate_event_url_pair_count"] == 0
    assert report["duplicate_query_plan_event_id_count"] == 0
    assert report["official_missing_events"] == []
    assert report["interaction_missing_events"] == []
    assert report["low_raw_events"] == {}


def test_retry_success_does_not_enter_errors_and_attempts_are_recorded():
    client = RetryThenSuccessClient()
    event = {"event_id": "E001", "time_window": {"start": "2025-01-01", "end": "2025-01-02"}}
    plan = {"query_rounds": [{"round": 1, "query": "retry q", "source_type": "news", "source_scope": ["news"]}]}
    errors = []
    attempts = []

    posts = collect_evidence_script._collect_for_plan(
        client,
        event,
        plan,
        max_results_per_query=1,
        max_evidence_per_event=1,
        max_queries_per_event=1,
        sleep_seconds=0,
        errors=errors,
        attempts=attempts,
    )

    assert len(posts) == 1
    assert errors == []
    assert attempts[0]["retry_count"] == 1
    assert [item["ok"] for item in attempts[0]["provider_attempts"]] == [False, True]


def test_forced_source_scope_overrides_event_source_scope():
    event = {
        "event_id": "e1",
        "event_name": "Transit plan",
        "seed_keywords": ["transit plan"],
        "source_scope": ["news", "official"],
    }

    forced = collect_evidence_script._with_forced_source_scope(event, ["news"])
    plan = plan_event_queries(forced, default_sources=["news"])
    coverage = evaluate_coverage(forced, [], default_sources=["news"])

    assert plan["query_rounds"][0]["source_scope"] == ["news"]
    assert list(coverage["source_coverage"]) == ["news"]
    assert event["source_scope"] == ["news", "official"]


def test_recollection_plan_builds_site_scoped_queries():
    plan = collect_evidence_script.plan_recollection_queries(
        {
            "event_id": "E1",
            "event_name": "Transit plan",
            "repair_keywords": ["Transit plan 官方回应"],
            "target_sources": ["official", "public_interaction"],
            "site_scope": ["gov.cn", "liuyan.people.com.cn"],
            "reason": ["official evidence missing"],
        }
    )

    query_texts = [item["query"] for item in plan["query_rounds"]]
    assert "site:gov.cn Transit plan 官方回应" in query_texts
    assert plan["query_rounds"][0]["source_scope"] == ["official", "public_interaction"]


def test_recollection_missing_api_creates_empty_output_and_debug(tmp_path):
    events = tmp_path / "recollection_plan.jsonl"
    config = tmp_path / "collector.yaml"
    output = tmp_path / "raw_posts_recollection.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"
    debug = tmp_path / "debug.json"

    events.write_text(
        '{"event_id":"E1","event_name":"Transit","repair_keywords":["Transit official"],'
        '"target_sources":["official"],"site_scope":["gov.cn"]}\n',
        encoding="utf-8",
    )
    config.write_text(
        """
search:
  provider: custom
  api_key: ""
  base_url: ""
collector:
  sleep_seconds: 0
""",
        encoding="utf-8",
    )

    code = collect_from_cli(
        Namespace(
            events=str(events),
            config=str(config),
            output=str(output),
            query_plan_output=str(query_plan),
            coverage_output=str(coverage),
            recollection=True,
            resume=False,
            max_events=1,
            max_queries_per_event=1,
            debug_output=str(debug),
            planner_debug_output=str(tmp_path / "planner_debug.json"),
        )
    )

    assert code == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8") == ""
    report = json.loads(debug.read_text(encoding="utf-8"))
    assert report["plan_rows_loaded"] == 1
    assert report["raw_posts_collected"] == 0


def test_resume_skips_completed_events_without_duplicate_outputs(tmp_path, monkeypatch, capsys):
    events = tmp_path / "events.jsonl"
    config = tmp_path / "collector.yaml"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"

    event_rows = [_formal_event("E001", "first"), _formal_event("E002", "second")]
    events.write_text("\n".join(json.dumps(row) for row in event_rows) + "\n", encoding="utf-8")
    config.write_text(
        """
search:
  provider: custom
  api_key: test-key
  base_url: https://search.test
collector:
  source_types:
    - news
  max_results_per_query: 1
  max_evidence_per_event: 1
  max_queries_per_event: 1
  max_repair_rounds: 0
  sleep_seconds: 0
""",
        encoding="utf-8",
    )
    output.write_text(
        json.dumps(
            {
                "raw_id": "raw_existing",
                "event_id": "E001",
                "query": "first",
                "query_round": 1,
                "source": "news",
                "url": "https://example.test/E001",
                "text": "existing first post",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    query_plan.write_text(
        json.dumps(plan_event_queries(event_rows[0], default_sources=["news"])) + "\n"
        + json.dumps(plan_event_queries(event_rows[1], default_sources=["news"])) + "\n",
        encoding="utf-8",
    )
    coverage.write_text(json.dumps({"events": {"E001": {"need_query_repair": False}}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(collect_evidence_script, "SearchClient", FakeSearchClient)

    code = collect_from_cli(
        Namespace(
            events=str(events),
            config=str(config),
            output=str(output),
            query_plan_output=str(query_plan),
            coverage_output=str(coverage),
            recollection=False,
            resume=True,
            max_events=None,
            max_queries_per_event=6,
            debug_output=str(tmp_path / "debug.json"),
            planner_debug_output=str(tmp_path / "planner_debug.json"),
        )
    )

    assert code == 0
    captured = capsys.readouterr().out
    assert "[resume] completed_events=1" in captured
    assert "[event 1/2] skip completed event_id=E001" in captured
    assert "[event 2/2] start event_id=E002" in captured
    raw_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["event_id"] for row in raw_rows] == ["E001", "E002"]
    assert len({row["raw_id"] for row in raw_rows}) == 2
    plan_rows = [json.loads(line) for line in query_plan.read_text(encoding="utf-8").splitlines()]
    assert [row["event_id"] for row in plan_rows] == ["E001", "E002"]
    report = json.load(coverage.open("r", encoding="utf-8"))
    assert report["num_events"] == 2
    assert set(report["events"]) == {"E001", "E002"}


def test_resume_preserves_existing_repair_artifacts(tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    config = tmp_path / "collector.yaml"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"

    event_rows = [_formal_event("E001", "first"), _formal_event("E002", "second")]
    events.write_text("\n".join(json.dumps(row) for row in event_rows) + "\n", encoding="utf-8")
    config.write_text(
        """
search:
  provider: custom
  api_key: test-key
  base_url: https://search.test
collector:
  source_types:
    - news
  max_results_per_query: 1
  max_evidence_per_event: 1
  max_queries_per_event: 1
  max_repair_rounds: 0
  sleep_seconds: 0
""",
        encoding="utf-8",
    )
    output.write_text(
        json.dumps({"raw_id": "raw_existing", "event_id": "E001", "query": "first", "source": "news", "url": "https://example.test/E001", "text": "existing"})
        + "\n",
        encoding="utf-8",
    )
    query_plan.write_text(
        json.dumps(plan_event_queries(event_rows[0], default_sources=["news"])) + "\n"
        + json.dumps(plan_event_queries(event_rows[1], default_sources=["news"])) + "\n",
        encoding="utf-8",
    )
    coverage.write_text(json.dumps({"events": {"E001": {"need_query_repair": False}}}) + "\n", encoding="utf-8")
    (tmp_path / "repair_collection_summary.json").write_text(
        json.dumps(
            {
                "events": {
                    "E001": {
                        "repair_queries": 3,
                        "first_pass_attempts": [
                            {
                                "event_id": "E001",
                                "query": "old",
                                "source_type": "news",
                                "provider_attempts": [{"attempt": 1, "ok": True, "final_status": "success"}],
                            }
                        ],
                        "repair_attempts": [],
                    }
                },
                "attempts": [{"event_id": "E001", "query": "old"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(collect_evidence_script, "SearchClient", FakeSearchClient)

    code = collect_from_cli(
        Namespace(
            events=str(events),
            config=str(config),
            output=str(output),
            query_plan_output=str(query_plan),
            coverage_output=str(coverage),
            recollection=False,
            resume=True,
            max_events=None,
            max_queries_per_event=6,
            debug_output=str(tmp_path / "debug.json"),
            planner_debug_output=str(tmp_path / "planner_debug.json"),
        )
    )

    assert code == 0
    repair_summary = json.loads((tmp_path / "repair_collection_summary.json").read_text(encoding="utf-8"))
    assert set(repair_summary["events"]) == {"E001", "E002"}
    assert any(item.get("event_id") == "E001" for item in repair_summary["attempts"])
    provider_attempt_summary = (tmp_path / "provider_attempt_summary.csv").read_text(encoding="utf-8")
    assert "E001" in provider_attempt_summary
    assert "old" in provider_attempt_summary


def test_repair_loop_writes_before_after_artifacts(tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    config = tmp_path / "collector.yaml"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"
    event_row = _formal_event("E001", "transit")
    event_row["source_scope"] = ["official", "news"]
    events.write_text(json.dumps(event_row) + "\n", encoding="utf-8")
    config.write_text(
        """
search:
  provider: custom
  api_key: test-key
  base_url: https://search.test
collector:
  source_types:
    - official
    - news
  max_results_per_query: 1
  max_evidence_per_event: 4
  max_queries_per_event: 2
  max_repair_rounds: 1
  min_raw_per_event: 1
  sleep_seconds: 0
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(collect_evidence_script, "SearchClient", RepairClient)

    code = collect_from_cli(
        Namespace(
            events=str(events),
            config=str(config),
            output=str(output),
            query_plan_output=str(query_plan),
            coverage_output=str(coverage),
            recollection=False,
            resume=False,
            max_events=None,
            max_queries_per_event=6,
            debug_output=str(tmp_path / "debug.json"),
            planner_debug_output=str(tmp_path / "planner_debug.json"),
        )
    )

    assert code == 0
    first_pass = json.loads((tmp_path / "first_pass_coverage.json").read_text(encoding="utf-8"))
    second_pass = json.loads((tmp_path / "second_pass_coverage.json").read_text(encoding="utf-8"))
    repair_queries = [json.loads(line) for line in (tmp_path / "repair_queries.jsonl").read_text(encoding="utf-8").splitlines()]
    official_repair_queries = [
        json.loads(line) for line in (tmp_path / "official_repair_queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    official_summary = json.loads((tmp_path / "official_repair_summary.json").read_text(encoding="utf-8"))
    failure_report = (tmp_path / "official_repair_failure_report.csv").read_text(encoding="utf-8")
    repair_summary = json.loads((tmp_path / "repair_collection_summary.json").read_text(encoding="utf-8"))
    delta = json.loads((tmp_path / "repair_delta_summary.json").read_text(encoding="utf-8"))
    raw_rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert first_pass["events"]["E001"]["need_query_repair"] is True
    assert second_pass["events"]["E001"]["source_coverage"]["official"] is True
    assert any(item["source_type"] == "official" for item in repair_queries)
    assert official_repair_queries
    assert official_summary["detected_official_count"] > 0
    assert "failure_reason" in failure_report
    assert repair_summary["events"]["E001"]["repair_queries"] > 0
    assert "event_seconds" in repair_summary["events"]["E001"]
    assert "source_seconds" in repair_summary["events"]["E001"]
    assert delta["events"]["E001"]["need_query_repair_before"] is True
    assert raw_rows[0]["source_type"] == "official"


class CountingClient:
    def __init__(self):
        self.calls = []

    def search(self, *, query, max_results, source_type=None, time_window=None):
        self.calls.append({"query": query, "source_type": source_type})
        return [
            {
                "title": query,
                "snippet": query,
                "text": query,
                "url": f"https://example.test/{query}",
                "source": source_type,
                "platform": source_type,
            }
        ][:max_results]


class FakeSearchClient:
    def __init__(self, config):
        self.config = config

    def search(self, *, query, max_results, source_type=None, time_window=None):
        return [
            {
                "title": query,
                "snippet": query,
                "text": query,
                "url": f"https://example.test/{query}",
                "source": source_type,
                "platform": source_type,
            }
        ][:max_results]


class SelectiveClient:
    def search_with_debug(self, *, query, max_results, source_type=None, time_window=None):
        if source_type == "forum":
            return {
                "query": query,
                "source_type": source_type,
                "results": [],
                "result_count": 0,
                "ok": True,
                "error": None,
                "error_type": None,
                "timeout": False,
            }
        results = [
            {
                "title": query,
                "snippet": query,
                "text": query,
                "url": f"https://www.gov.cn/{query}" if source_type == "official" else f"https://example.test/{source_type}/{query}",
                "source": source_type,
                "platform": source_type,
            }
        ][:max_results]
        return {
            "query": query,
            "source_type": source_type,
            "results": results,
            "result_count": len(results),
            "ok": True,
            "error": None,
            "error_type": None,
            "timeout": False,
        }


class MixedOfficialClient:
    def search_with_debug(self, *, query, max_results, source_type=None, time_window=None):
        results = [
            {
                "title": "新闻转载政府公告",
                "snippet": "新闻转载",
                "text": "新闻转载政府公告",
                "url": "https://news.sohu.com/a/1",
                "source": source_type,
                "platform": source_type,
            },
            {
                "title": "金钻豪园项目批复",
                "snippet": "政务公开 信息公开",
                "text": "金钻豪园项目批复 政务公开 信息公开",
                "url": "https://www.sz.gov.cn/xxgk/a.html",
                "source": source_type,
                "platform": source_type,
            },
        ][:max_results]
        return {
            "query": query,
            "source_type": source_type,
            "results": results,
            "result_count": len(results),
            "ok": True,
            "error": None,
            "error_type": None,
            "timeout": False,
        }


class RetryThenSuccessClient:
    config = type("Config", (), {"provider": "custom"})()

    def search_with_debug(self, *, query, max_results, source_type=None, time_window=None):
        del max_results, time_window
        return {
            "query": query,
            "source_type": source_type,
            "results": [
                {
                    "title": query,
                    "snippet": "居民投诉质疑，部门回应整改完成后续追踪。",
                    "text": "居民投诉质疑，部门回应整改完成后续追踪。",
                    "url": "https://example.test/retry",
                    "source": source_type,
                    "platform": source_type,
                }
            ],
            "result_count": 1,
            "ok": True,
            "error": None,
            "error_type": None,
            "timeout": False,
            "retry_count": 1,
            "final_status": "success",
            "provider_attempts": [
                {"attempt": 1, "ok": False, "error_type": "ConnectTimeout", "duration_seconds": 1.0, "final_status": "failed"},
                {"attempt": 2, "ok": True, "error_type": None, "duration_seconds": 0.1, "final_status": "success"},
            ],
        }


class RepairClient:
    official_calls = 0

    def __init__(self, config):
        self.config = config
        type(self).official_calls = 0

    def search_with_debug(self, *, query, max_results, source_type=None, time_window=None):
        if source_type == "official":
            type(self).official_calls += 1
            if type(self).official_calls <= 2:
                return self._response(query, source_type, [])
            return self._response(
                query,
                source_type,
                [
                    {
                        "title": query,
                        "snippet": "居民投诉质疑改造方案，政府部门回应说明，整改完成后续追踪。",
                        "text": "居民投诉质疑改造方案，政府部门回应说明，整改完成后续追踪。",
                        "url": f"https://www.gov.cn/{type(self).official_calls}",
                        "source": source_type,
                        "platform": source_type,
                    }
                ],
            )
        return self._response(query, source_type, [])

    def _response(self, query, source_type, results):
        return {
            "query": query,
            "source_type": source_type,
            "results": results,
            "result_count": len(results),
            "ok": True,
            "error": None,
            "error_type": None,
            "timeout": False,
        }


def _formal_event(event_id: str, seed: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "event_name": f"{seed} event",
        "event_description": f"A concrete public {seed} event in Test City",
        "location": {"city": "Test City"},
        "time_window": {"start": "2025-01-01", "end": "2025-01-02"},
        "trigger": f"{seed} trigger",
        "anchor_entities": {"government": "Test City Council"},
        "anchor_urls": [f"https://source.test/{event_id}"],
        "query_seeds": [seed],
        "source_scope": ["news"],
        "domain": "urban_mobility",
        "event_type": "concrete_event",
        "stakeholder_hints": ["residents"],
        "stance_hints": ["concern"],
        "temporal_stages": ["trigger"],
    }
