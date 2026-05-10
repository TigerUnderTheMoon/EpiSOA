import csv
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBSET_SCRIPT = ROOT / "scripts" / "run_query_planner_diagnostic_subset.py"
ANALYZE_SCRIPT = ROOT / "scripts" / "analyze_query_planner_ablation.py"

subset_spec = importlib.util.spec_from_file_location("query_planner_diagnostic_subset", SUBSET_SCRIPT)
subset_script = importlib.util.module_from_spec(subset_spec)
assert subset_spec.loader is not None
subset_spec.loader.exec_module(subset_script)

analyze_spec = importlib.util.spec_from_file_location("query_planner_ablation_analysis", ANALYZE_SCRIPT)
analyze_script = importlib.util.module_from_spec(analyze_spec)
assert analyze_spec.loader is not None
analyze_spec.loader.exec_module(analyze_script)


def test_subset_manifest_is_reproducible(tmp_path):
    events_path = tmp_path / "events.jsonl"
    config_path = tmp_path / "collector.yaml"
    events_path.write_text("\n".join(json.dumps(_event(i), ensure_ascii=False) for i in range(1, 13)) + "\n", encoding="utf-8")
    config_path.write_text(_config_text(), encoding="utf-8")

    result_a = subset_script.run_diagnostic_subset(
        config_path=config_path,
        events_path=events_path,
        output_dir=tmp_path / "run_a",
        manifest_path=tmp_path / "run_a" / "manifest.json",
        num_events=10,
        seed=7,
        dry_run=True,
        manifest_only=True,
    )
    result_b = subset_script.run_diagnostic_subset(
        config_path=config_path,
        events_path=events_path,
        output_dir=tmp_path / "run_b",
        manifest_path=tmp_path / "run_b" / "manifest.json",
        num_events=10,
        seed=7,
        dry_run=True,
        manifest_only=True,
    )

    assert result_a["event_ids"] == result_b["event_ids"]
    manifest = json.loads((tmp_path / "run_a" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["num_selected"] == 10
    assert all(item["selection_rationale"] for item in manifest["events"])


def test_analysis_paired_integrity_and_output_schema(tmp_path):
    per_event = tmp_path / "per_event.csv"
    summary = tmp_path / "summary.csv"
    output_dir = tmp_path / "analysis"
    _write_csv(
        per_event,
        [
            _ablation_row("E001", "heuristic", initial_entity=0.5, final_entity=0.7, calls=10, probes=0),
            _ablation_row("E001", "ga", initial_entity=1.0, final_entity=1.0, calls=15, probes=5),
            _ablation_row("E002", "heuristic", initial_entity=1.0, final_entity=1.0, calls=8, probes=0),
            _ablation_row("E002", "ga", initial_entity=0.5, final_entity=1.0, calls=20, probes=10),
        ],
        analyze_script.NUMERIC_METRICS,
    )
    _write_csv(summary, [{"condition": "heuristic"}, {"condition": "ga"}, {"condition": "ga_minus_heuristic"}], [])

    result = analyze_script.analyze_ablation(
        per_event_path=per_event,
        summary_path=summary,
        output_dir=output_dir,
        top_k=2,
    )

    assert result["status"] == "completed"
    assert result["num_events"] == 2
    paired = _read_csv(output_dir / "query_planner_ablation_paired_differences.csv")
    assert {row["event_id"] for row in paired} == {"E001", "E002"}
    assert "ga_value_score" in paired[0]
    analysis = json.loads((output_dir / "query_planner_ablation_analysis_summary.json").read_text(encoding="utf-8"))
    assert "initial_entity_coverage" in analysis["aggregate_diagnostics"]
    assert (output_dir / "query_planner_ablation_ga_helps_most.csv").exists()
    assert (output_dir / "query_planner_ablation_ga_hurts_most.csv").exists()


def _event(index: int) -> dict:
    source_scope = ["news", "official", "forum", "public_social"] if index % 3 else ["news", "official"]
    anchor_entities = {"community": f"社区{index}", "government": f"部门{index}", "project": f"项目{index}"}
    if index % 4 == 0:
        anchor_entities = {"site": f"地点{index}"}
    return {
        "event_id": f"E{index:03d}",
        "domain": "urban_renewal",
        "event_type": "concrete_event",
        "event_name": f"事件{index}",
        "event_description": f"具体公共事件{index}",
        "location": {"city": "测试市"},
        "time_window": {"start": "2025-01-01", "end": "2025-01-02"},
        "trigger": f"触发事件{index}",
        "anchor_entities": anchor_entities,
        "anchor_urls": [f"https://example.test/{index}"],
        "source_scope": source_scope,
        "query_seeds": [f"事件{index} 查询", f"事件{index} 回应"],
        "stakeholder_hints": [f"居民{index}", f"部门{index}"],
        "stance_hints": ["支持", "质疑", "回应"],
        "temporal_stages": ["trigger", "conflict", "response"],
    }


def _ablation_row(event_id: str, condition: str, *, initial_entity: float, final_entity: float, calls: int, probes: int) -> dict:
    row = {metric: 0 for metric in analyze_script.NUMERIC_METRICS}
    row.update(
        {
            "event_id": event_id,
            "condition": condition,
            "initial_entity_coverage": initial_entity,
            "initial_source_coverage": initial_entity,
            "final_entity_coverage": final_entity,
            "final_source_coverage": final_entity,
            "total_api_calls": calls,
            "probe_api_calls": probes,
            "num_repair_rounds": 0,
            "num_repair_queries": 0,
            "initial_need_query_repair": 0,
        }
    )
    return row


def _write_csv(path: Path, rows: list[dict], numeric_columns: list[str]) -> None:
    columns = ["event_id", "condition", *numeric_columns] if numeric_columns else ["condition"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _config_text() -> str:
    return """
search:
  provider: custom
  api_key: ""
  base_url: ""
collector:
  source_types:
    - news
    - official
    - forum
    - public_social
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
