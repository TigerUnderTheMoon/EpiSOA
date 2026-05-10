import csv
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_query_planner_ablation.py"
SPEC = importlib.util.spec_from_file_location("query_planner_ablation_script", SCRIPT_PATH)
ablation_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ablation_script)


class RepairOnlySearchClient:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, *, query, max_results, source_type=None, time_window=None):
        self.calls += 1
        if "trigger" not in str(query):
            return []
        return [
            {
                "title": f"{query} Central Park",
                "snippet": "official agency response",
                "text": "Central Park City agency trigger conflict response",
                "url": f"https://fixture.test/{source_type}/{self.calls}",
                "source": source_type,
                "platform": source_type,
            }
        ][:max_results]

    def search_with_debug(self, *, query, max_results, source_type=None, time_window=None):
        return {
            "ok": True,
            "error": None,
            "error_type": None,
            "results": self.search(query=query, max_results=max_results, source_type=source_type, time_window=time_window),
        }


def test_ablation_writes_metric_schema_and_paired_events(tmp_path):
    events_path = tmp_path / "events.jsonl"
    config_path = tmp_path / "collector.yaml"
    output_dir = tmp_path / "ablation"
    events_path.write_text(
        json.dumps(_event("E001"), ensure_ascii=False) + "\n" + json.dumps(_event("E002"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    config_path.write_text(_config_text(), encoding="utf-8")

    result = ablation_script.run_ablation(
        config_path=config_path,
        events_path=events_path,
        output_dir=output_dir,
        dry_run=True,
    )

    assert result["status"] == "completed"
    per_event_rows = _read_csv(output_dir / "query_planner_ablation_per_event.csv")
    assert list(per_event_rows[0]) == ablation_script.PER_EVENT_COLUMNS
    assert {(row["event_id"], row["condition"]) for row in per_event_rows} == {
        ("E001", "heuristic"),
        ("E001", "ga"),
        ("E002", "heuristic"),
        ("E002", "ga"),
    }
    summary = json.loads((output_dir / "query_planner_ablation_summary.json").read_text(encoding="utf-8"))
    assert "heuristic" in summary["conditions"]
    assert "ga" in summary["conditions"]
    assert "initial_source_coverage" in summary["paired_differences"]


def test_initial_and_final_metrics_are_captured_separately():
    event = _event("E001")
    rows = ablation_script._run_condition(
        condition="heuristic",
        events=[event],
        collector_config={
            "source_types": ["news"],
            "max_results_per_query": 1,
            "max_evidence_per_event": 2,
        },
        client=ablation_script.CountingSearchClient(RepairOnlySearchClient()),
    )

    row = rows[0]
    assert row["initial_source_coverage"] == 0
    assert row["final_source_coverage"] == 1
    assert row["num_repair_rounds"] == 1
    assert row["repair_api_calls"] > 0


def test_ablation_output_is_deterministic_with_fixture_mode(tmp_path):
    events_path = tmp_path / "events.jsonl"
    config_path = tmp_path / "collector.yaml"
    events_path.write_text(json.dumps(_event("E001"), ensure_ascii=False) + "\n", encoding="utf-8")
    config_path.write_text(_config_text(), encoding="utf-8")

    ablation_script.run_ablation(
        config_path=config_path,
        events_path=events_path,
        output_dir=tmp_path / "run_a",
        dry_run=True,
    )
    ablation_script.run_ablation(
        config_path=config_path,
        events_path=events_path,
        output_dir=tmp_path / "run_b",
        dry_run=True,
    )

    assert (tmp_path / "run_a" / "query_planner_ablation_per_event.csv").read_text(encoding="utf-8") == (
        tmp_path / "run_b" / "query_planner_ablation_per_event.csv"
    ).read_text(encoding="utf-8")
    assert (tmp_path / "run_a" / "query_planner_ablation_summary.csv").read_text(encoding="utf-8") == (
        tmp_path / "run_b" / "query_planner_ablation_summary.csv"
    ).read_text(encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _event(event_id: str) -> dict:
    return {
        "event_id": event_id,
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
        "stakeholder_hints": ["residents", "agency"],
        "stance_hints": ["support", "concern"],
        "temporal_stages": ["trigger", "conflict", "response"],
    }


def _config_text() -> str:
    return """
search:
  provider: custom
  api_key: ""
  base_url: ""
collector:
  source_types:
    - news
  max_results_per_query: 1
  max_evidence_per_event: 2
  sleep_seconds: 0
  query_planner:
    mode: heuristic
    ga:
      enabled: false
      population_size: 4
      generations: 1
      individual_size: 2
      tournament_size: 2
      mutation_rate: 0.25
      probe_max_results_per_query: 1
      random_seed: 42
"""
