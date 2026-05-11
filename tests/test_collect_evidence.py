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

    assert plan["query_rounds"][0]["source_scope"] == ["news", "public_social"]
    assert "social_media" not in coverage["source_coverage"]
    assert "public_social" in coverage["source_coverage"]
    assert coverage["temporal_stage_coverage_mode"] == "literal_string_match_legacy"


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
