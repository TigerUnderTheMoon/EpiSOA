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
        '{"event_id":"e1","topic_id":"T001","event_name":"Transit plan vote",'
        '"event_description":"A concrete transit plan vote in Test City",'
        '"location":{"city":"Test City"},"time_window":{"start":"2025-01-01","end":"2025-01-02"},'
        '"trigger":"city council vote","anchor_entities":["Test City Council"],'
        '"anchor_urls":["https://source.test/event"],"queries":["transit plan"],'
        '"source_scope":["news"],"selection_status":"accepted","instance_version":"v1",'
        '"seed_keywords":["transit plan"],"stakeholder_hints":["residents"],"stance_hints":["concern"]}\n',
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
            max_events=None,
            max_queries_per_event=6,
            debug_output=str(tmp_path / "debug.json"),
        )
    )

    assert code == 0
    assert output.read_text(encoding="utf-8") == ""
    plan = [json.loads(line) for line in query_plan.read_text(encoding="utf-8").splitlines()]
    report = json.loads(coverage.read_text(encoding="utf-8"))
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

    queries = [item["query"] for item in plan["query_rounds"]]
    assert "site:gov.cn Transit plan 官方回应" in queries
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
            max_events=1,
            max_queries_per_event=1,
            debug_output=str(debug),
        )
    )

    assert code == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8") == ""
    report = json.loads(debug.read_text(encoding="utf-8"))
    assert report["plan_rows_loaded"] == 1
    assert report["raw_posts_collected"] == 0
