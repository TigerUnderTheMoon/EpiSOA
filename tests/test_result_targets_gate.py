import json
from pathlib import Path

from scripts.check_result_targets import run_gate


REQUIRED_ARTIFACTS = [
    "verified_soa_tuples.jsonl",
    "candidate_soa_tuples.jsonl",
    "metric_threshold_sensitivity.csv",
    "tuple_failure_audit.csv",
]


def test_stage_guard_fails_when_full_soe_has_empty_regression_event(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_setting(runs_dir, "full_soe", f1_03=0.75, f1_05=0.72, empty_events=["E046"])
    write_setting(runs_dir, "without_soe_graph", f1_03=0.70, f1_05=0.70)

    result = run_gate(runs_dir=runs_dir, mode="stage-guard")

    assert result["status"] == "failed"
    assert any("E046" in issue for issue in result["issues"])


def test_stage_guard_passes_for_complete_full_soe_improvement(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.72)
    write_setting(runs_dir, "without_soe_graph", f1_03=0.70, f1_05=0.70)

    result = run_gate(runs_dir=runs_dir, mode="stage-guard")

    assert result["status"] == "passed"
    assert result["comparisons"]["full_soe_vs_without_soe_graph"]["Tuple-F1-semantic@0.3_delta"] == 0.06


def test_stage_guard_uses_semantic_05_for_no_graph_win_gate(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.70)
    write_setting(runs_dir, "without_soe_graph", f1_03=0.70, f1_05=0.70)

    result = run_gate(runs_dir=runs_dir, mode="stage-guard")

    assert result["status"] == "failed"
    assert any(
        "Tuple-F1-semantic@0.5" in issue and "without_soe_graph" in issue
        for issue in result["issues"]
    )


def test_final_gate_requires_main_targets_and_non_oracle_ablation_lead(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_json(
        main_dir / "metrics.json",
        {
            "Metric-Scope": "gold_event_scope",
            "Tuple-F1-semantic": 0.71,
            "Tuple-Precision-semantic": 0.72,
            "Tuple-Recall-semantic": 0.73,
            "Tuple-F1-semantic@0.25": 0.78,
            "Tuple-F1-semantic@0.3": 0.76,
            "Tuple-F1-semantic@0.5": 0.71,
        },
    )
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.71, f1_025=0.78)
    write_setting(runs_dir, "direct_llm", f1_03=0.70, f1_05=0.65, f1_025=0.72)
    write_setting(runs_dir, "oracle_evidence", f1_03=0.80, f1_05=0.75, f1_025=0.82)
    write_json(
        runs_dir / "ablation_summary.json",
        {"status": "completed", "settings": ["full_soe", "direct_llm", "oracle_evidence"]},
    )

    result = run_gate(runs_dir=runs_dir, mode="final", main_dir=main_dir)

    assert result["status"] == "passed"
    assert result["ignored_settings_for_best_check"] == ["oracle_evidence"]


def test_final_gate_accepts_lower_nonzero_semantic_05_after_metric_policy_change(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_json(
        main_dir / "metrics.json",
        {
            "Metric-Scope": "gold_event_scope",
            "Tuple-F1-semantic": 0.1468,
            "Tuple-Precision-semantic": 0.3636,
            "Tuple-Recall-semantic": 0.092,
            "Tuple-F1-semantic@0.5": 0.1468,
        },
    )
    write_setting(runs_dir, "full_soe", f1_03=0.2385, f1_05=0.1468, f1_025=0.2477)
    write_setting(runs_dir, "direct_llm", f1_03=0.05, f1_05=0.04, f1_025=0.06)
    write_json(
        runs_dir / "ablation_summary.json",
        {"status": "completed", "settings": ["full_soe", "direct_llm"]},
    )

    result = run_gate(runs_dir=runs_dir, mode="final", main_dir=main_dir)

    assert result["status"] == "passed"


def test_final_gate_fails_when_non_oracle_variant_matches_main(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_json(
        main_dir / "metrics.json",
        {
            "Metric-Scope": "gold_event_scope",
            "Tuple-F1-semantic": 0.71,
            "Tuple-Precision-semantic": 0.72,
            "Tuple-Recall-semantic": 0.73,
            "Tuple-F1-semantic@0.25": 0.78,
            "Tuple-F1-semantic@0.3": 0.76,
            "Tuple-F1-semantic@0.5": 0.71,
        },
    )
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.71, f1_025=0.78)
    write_setting(runs_dir, "direct_llm", f1_03=0.70, f1_05=0.71, f1_025=0.72)
    write_json(
        runs_dir / "ablation_summary.json",
        {"status": "completed", "settings": ["full_soe", "direct_llm"]},
    )

    result = run_gate(runs_dir=runs_dir, mode="final", main_dir=main_dir)

    assert result["status"] == "failed"
    assert any("direct_llm" in issue and "Tuple-F1-semantic@0.5" in issue for issue in result["issues"])


def test_final_gate_checks_without_soe_graph_as_real_control(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_json(
        main_dir / "metrics.json",
        {
            "Metric-Scope": "gold_event_scope",
            "Tuple-F1-semantic": 0.73,
            "Tuple-Precision-semantic": 0.72,
            "Tuple-Recall-semantic": 0.75,
        },
    )
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.71, f1_025=0.78)
    write_setting(runs_dir, "without_soe_graph", f1_03=0.76, f1_05=0.71, f1_025=0.78)
    write_setting(runs_dir, "direct_llm", f1_03=0.70, f1_05=0.65, f1_025=0.72)
    write_json(
        runs_dir / "ablation_summary.json",
        {
            "status": "completed",
            "settings": ["full_soe", "without_soe_graph", "direct_llm"],
            "reuse": {
                "without_soe_graph": {
                    "source_setting": "full_soe",
                    "reason": "same_setting_fingerprint",
                }
            },
        },
    )

    result = run_gate(runs_dir=runs_dir, mode="final", main_dir=main_dir)

    assert result["status"] == "failed"
    assert result["ignored_settings_for_best_check"] == []
    assert any(
        "without_soe_graph" in issue and "Tuple-F1-semantic@0.5" in issue
        for issue in result["issues"]
    )


def test_final_gate_rejects_all_parse_failed_setting(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_json(
        main_dir / "metrics.json",
        {
            "Metric-Scope": "gold_event_scope",
            "Tuple-F1-semantic": 0.71,
            "Tuple-Precision-semantic": 0.72,
            "Tuple-Recall-semantic": 0.73,
        },
    )
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.71, f1_025=0.78)
    write_setting(runs_dir, "direct_llm", f1_03=0.0, f1_05=0.0, f1_025=0.0)
    write_json(
        runs_dir / "ablation_direct_llm" / "schema_attribution_summary.json",
        {
            "num_events_requested": 2,
            "num_events_skipped": 0,
            "num_tuples_generated": 0,
            "num_api_calls": 4,
            "parse_failed_events": ["E001", "E002"],
        },
    )
    write_json(
        runs_dir / "ablation_summary.json",
        {"status": "completed", "settings": ["full_soe", "direct_llm"]},
    )

    result = run_gate(runs_dir=runs_dir, mode="final", main_dir=main_dir)

    assert result["status"] == "failed"
    assert any("direct_llm" in issue and "zero parsed attribution tuples" in issue for issue in result["issues"])


def test_final_gate_checks_main_semantic_05_threshold(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_json(
        main_dir / "metrics.json",
        {
            "Metric-Scope": "gold_event_scope",
            "Tuple-F1-semantic": 0.73,
            "Tuple-Precision-semantic": 0.72,
            "Tuple-Recall-semantic": 0.75,
        },
    )
    write_setting(runs_dir, "full_soe", f1_03=0.76, f1_05=0.71, f1_025=0.78)
    write_setting(runs_dir, "direct_llm", f1_03=0.70, f1_05=0.80, f1_025=0.72)
    write_json(
        runs_dir / "ablation_summary.json",
        {"status": "completed", "settings": ["full_soe", "direct_llm"]},
    )

    result = run_gate(runs_dir=runs_dir, mode="final", main_dir=main_dir)

    assert result["status"] == "failed"
    assert any("direct_llm" in issue and "Tuple-F1-semantic@0.5" in issue for issue in result["issues"])


def write_setting(
    runs_dir: Path,
    setting: str,
    *,
    f1_03: float,
    f1_05: float,
    f1_025: float | None = None,
    empty_events: list[str] | None = None,
) -> None:
    setting_dir = runs_dir / f"ablation_{setting}"
    setting_dir.mkdir(parents=True)
    metrics = {
        "Metric-Scope": "gold_event_scope",
        "Tuple-F1-semantic": f1_05,
        "Tuple-Precision-semantic": 0.75,
        "Tuple-Recall-semantic": 0.75,
        "Tuple-F1-semantic@0.25": f1_025 if f1_025 is not None else f1_03,
        "Tuple-F1-semantic@0.3": f1_03,
        "Tuple-F1-semantic@0.5": f1_05,
    }
    write_json(setting_dir / "metrics.json", metrics)
    write_json(setting_dir / "scoring_scope.json", {"excluded_prediction_count": 0})
    write_json(setting_dir / "schema_attribution_summary.json", {"empty_tuple_events": empty_events or []})
    for name in REQUIRED_ARTIFACTS:
        (setting_dir / name).write_text("", encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
