from argparse import Namespace
import importlib.util
import json
from pathlib import Path

from episoa.collector.genetic_query_planner import (
    GeneticPlannerConfig,
    ProbeCache,
    build_candidate_query_pool,
    fitness_for_individual,
    plan_event_queries_ga,
)
from episoa.collector.query_planner import plan_event_queries


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "collect_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_evidence_script", SCRIPT_PATH)
collect_evidence_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collect_evidence_script)


class FakeSearchConfig:
    configured = True


class FakeSearchClient:
    def __init__(self) -> None:
        self.calls = 0

    def search_with_debug(self, *, query, max_results, source_type=None, time_window=None):
        self.calls += 1
        return {
            "ok": True,
            "error": None,
            "error_type": None,
            "results": [
                {
                    "title": f"{query} Central Park residents support",
                    "snippet": "City agency response and project update",
                    "text": "Central Park residents support agency response",
                    "url": f"https://example.test/{source_type}/{abs(hash(query)) % 1000}",
                    "source": source_type,
                    "platform": source_type,
                }
            ][:max_results],
        }


def test_candidate_pool_generation_is_deterministic_and_deduplicated():
    event = _event(stakeholder_hints=["residents"], stance_hints=["support"])

    first = build_candidate_query_pool(event)
    second = build_candidate_query_pool(event)

    assert first == second
    assert len(first) == len(set(first))
    assert "park renovation" in first
    assert "park renovation Central Park" in first
    assert "park renovation residents support" in first


def test_candidate_pool_works_without_optional_hints():
    pool = build_candidate_query_pool(_event(stakeholder_hints=None, stance_hints=None))

    assert "park renovation Central Park" in pool
    assert all("None" not in item for item in pool)


def test_fitness_omits_missing_optional_hint_components():
    event = _event(stakeholder_hints=None, stance_hints=None)
    cache = ProbeCache()
    score, breakdown = fitness_for_individual(
        event,
        ["park renovation"],
        ["news"],
        FakeSearchClient(),
        GeneticPlannerConfig(enabled=True, individual_size=1),
        cache,
    )

    assert score > 0
    assert breakdown["stakeholder_coverage"] == 0
    assert breakdown["stance_diversity"] == 0


def test_fitness_calculation_uses_synthetic_probe_results():
    event = _event(stakeholder_hints=["residents"], stance_hints=["support"])
    cache = ProbeCache()
    score, breakdown = fitness_for_individual(
        event,
        ["park renovation"],
        ["news"],
        FakeSearchClient(),
        GeneticPlannerConfig(enabled=True, individual_size=1),
        cache,
    )

    assert score > 0
    assert breakdown["relevance"] > 0
    assert breakdown["entity_coverage"] > 0
    assert breakdown["source_coverage"] == 1
    assert breakdown["traceability"] == 1


def test_probe_cache_hits_on_repeated_query():
    event = _event()
    client = FakeSearchClient()
    cache = ProbeCache()
    config = GeneticPlannerConfig(enabled=True, individual_size=1)

    fitness_for_individual(event, ["park renovation"], ["news"], client, config, cache)
    fitness_for_individual(event, ["park renovation"], ["news"], client, config, cache)

    assert client.calls == 1
    assert cache.stats()["hits"] == 1


def test_ga_reproducible_with_fixed_seed_and_outputs_query_plan_shape():
    event = _event(stakeholder_hints=["residents"], stance_hints=["support"])
    config = GeneticPlannerConfig(enabled=True, population_size=6, generations=2, individual_size=3, random_seed=7)

    plan_a, debug_a = plan_event_queries_ga(event, client=FakeSearchClient(), default_sources=["news"], config=config)
    plan_b, debug_b = plan_event_queries_ga(event, client=FakeSearchClient(), default_sources=["news"], config=config)

    assert [item["query"] for item in plan_a["query_rounds"]] == [item["query"] for item in plan_b["query_rounds"]]
    assert debug_a["best_fitness"] == debug_b["best_fitness"]
    assert plan_a["query_rounds"][0]["generated_by"] == "coverage_aware_ga_query_planning"


def test_heuristic_mode_matches_existing_planner():
    event = _event(stakeholder_hints=["residents"], stance_hints=["support"])
    direct = plan_event_queries(event, default_sources=["news"])
    script = collect_evidence_script.build_initial_query_plans(
        events=[event],
        planner_mode="heuristic",
        planner_config={},
        search_config=FakeSearchConfig(),
        default_sources=["news"],
    )[0][0]

    assert script == direct


def test_ga_does_not_run_for_empty_events_or_invalid_formal_event(tmp_path):
    config = tmp_path / "collector.yaml"
    events = tmp_path / "events.jsonl"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"
    planner_debug = tmp_path / "planner_debug.json"
    events.write_text("", encoding="utf-8")
    config.write_text(_ga_config_text(api_key="key", base_url="https://example.test"), encoding="utf-8")

    code = collect_evidence_script.collect_from_cli(
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
            planner_debug_output=str(planner_debug),
        )
    )

    assert code == 0
    assert json.loads(planner_debug.read_text(encoding="utf-8"))["events"] == []

    events.write_text('{"event_id":"E1","event_name":"Broken"}\n', encoding="utf-8")
    code = collect_evidence_script.collect_from_cli(
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
            planner_debug_output=str(planner_debug),
        )
    )
    assert code == 1


def test_ga_planned_only_without_search_config_falls_back_to_heuristic(tmp_path):
    config = tmp_path / "collector.yaml"
    events = tmp_path / "events.jsonl"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"
    planner_debug = tmp_path / "planner_debug.json"
    events.write_text(json.dumps(_event(stakeholder_hints=["residents"], stance_hints=["support"]), ensure_ascii=False) + "\n", encoding="utf-8")
    config.write_text(_ga_config_text(api_key="", base_url=""), encoding="utf-8")

    code = collect_evidence_script.collect_from_cli(
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
            planner_debug_output=str(planner_debug),
        )
    )

    assert code == 0
    rows = [json.loads(line) for line in query_plan.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["query_rounds"][0]["generated_by"] == "cfsm_s1_query_planning"
    assert json.loads(planner_debug.read_text(encoding="utf-8"))["events"][0]["planner_mode"] == "heuristic"


def test_recollection_mode_remains_unchanged(tmp_path):
    config = tmp_path / "collector.yaml"
    events = tmp_path / "recollection.jsonl"
    output = tmp_path / "raw_posts.jsonl"
    query_plan = tmp_path / "query_plan.jsonl"
    coverage = tmp_path / "coverage.json"
    planner_debug = tmp_path / "planner_debug.json"
    events.write_text('{"event_id":"E1","repair_keywords":["repair"],"target_sources":["official"]}\n', encoding="utf-8")
    config.write_text(_ga_config_text(api_key="", base_url=""), encoding="utf-8")

    code = collect_evidence_script.collect_from_cli(
        Namespace(
            events=str(events),
            config=str(config),
            output=str(output),
            query_plan_output=str(query_plan),
            coverage_output=str(coverage),
            recollection=True,
            max_events=None,
            max_queries_per_event=1,
            debug_output=str(tmp_path / "debug.json"),
            planner_debug_output=str(planner_debug),
        )
    )

    assert code == 0
    rows = [json.loads(line) for line in query_plan.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["query_rounds"][0]["generated_by"] == "quality_filter_recollection_plan"


def _event(stakeholder_hints=None, stance_hints=None):
    event = {
        "event_id": "E001",
        "domain": "urban_renewal",
        "event_type": "concrete_event",
        "event_name": "Central Park renovation dispute",
        "event_description": "Residents debated a park renovation plan.",
        "location": {"city": "Test City"},
        "time_window": {"start": "2025-01-01", "end": "2025-01-02"},
        "trigger": "City agency released the park renovation plan",
        "anchor_entities": {"community": "Central Park", "government": "City agency"},
        "anchor_urls": ["https://example.test/event"],
        "source_scope": ["news"],
        "query_seeds": ["park renovation", "Central Park plan"],
        "temporal_stages": ["trigger", "conflict", "response"],
    }
    if stakeholder_hints is not None:
        event["stakeholder_hints"] = stakeholder_hints
    if stance_hints is not None:
        event["stance_hints"] = stance_hints
    return event


def _ga_config_text(api_key: str, base_url: str) -> str:
    return f"""
search:
  provider: custom
  api_key: "{api_key}"
  base_url: "{base_url}"
collector:
  source_types:
    - news
  max_results_per_query: 1
  max_evidence_per_event: 1
  sleep_seconds: 0
  query_planner:
    mode: ga
    ga:
      enabled: true
      population_size: 4
      generations: 1
      individual_size: 2
      tournament_size: 2
      mutation_rate: 0.25
      probe_max_results_per_query: 1
      random_seed: 42
"""
