from pathlib import Path

from episoa.data.schema import PredictionTuple
from episoa.config import load_config
from episoa.pipeline import (
    ABLATION_SETTINGS,
    PIPELINE_FLAG_KEYS,
    _apply_verifier_quality_gate,
    _ablation_main_result,
    _formal_model_provenance_warnings,
    _formal_result_status,
    paper_status,
)


def test_paper_status_returns_valid_structure() -> None:
    status = paper_status()

    assert "paper_readiness" in status
    assert isinstance(status["paper_readiness"]["data_ready"], bool)
    assert isinstance(status["paper_readiness"]["events_ready"], bool)
    assert isinstance(status["paper_readiness"]["formal_results_ready"], bool)
    assert "formal_results" in status
    assert "dataset" in status
    assert "num_gold_tuples" in status["dataset"]
    assert status["next_commands"] is not None
    if Path("outputs/runs_human_gold_v2/ablation_results.csv").exists():
        assert status["artifacts"]["ablation_results.csv"] is True


def test_formal_result_status_requires_canonical_full_soe_metrics(tmp_path) -> None:
    status = _formal_result_status(tmp_path / "runs")

    assert status["ready"] is False
    assert "ablation_full_soe/metrics.json" in status["missing"]


def test_formal_result_status_rejects_empty_outputs_and_total_parse_failure(tmp_path) -> None:
    setting_dir = tmp_path / "runs" / "ablation_full_soe"
    setting_dir.mkdir(parents=True)
    for name in (
        "metrics.json",
        "scoring_scope.json",
        "verified_soa_tuples.jsonl",
        "metric_threshold_sensitivity.csv",
        "tuple_failure_audit.csv",
    ):
        (setting_dir / name).write_text("{}\n", encoding="utf-8")
    (setting_dir / "candidate_soa_tuples.jsonl").write_text("", encoding="utf-8")
    (setting_dir / "schema_attribution_summary.json").write_text(
        (
            '{"num_api_calls": 3, "num_tuples_generated": 0, '
            '"num_events_requested": 3, "num_events_skipped": 0, '
            '"parse_failed_events": ["E001", "E002", "E003"]}'
        ),
        encoding="utf-8",
    )

    status = _formal_result_status(tmp_path / "runs")

    assert status["ready"] is False
    assert "ablation_full_soe/candidate_soa_tuples.jsonl" in status["empty"]
    assert any("zero parsed attribution tuples" in issue for issue in status["health_issues"])


def test_formal_model_provenance_warnings_flag_stale_manifest_model(tmp_path) -> None:
    setting_dir = tmp_path / "runs" / "ablation_full_soe"
    setting_dir.mkdir(parents=True)
    (setting_dir / "input_manifest.json").write_text(
        '{"model": {"model_name": "gpt-5.5", "base_url_env": "OPENAI_BASE_URL"}}',
        encoding="utf-8",
    )

    warnings = _formal_model_provenance_warnings(
        {"model_name": "deepseek-v4-flash", "base_url_env": "DEEPSEEK_BASE_URL"},
        tmp_path / "runs",
    )

    assert any("model_name mismatch" in warning for warning in warnings)
    assert any("base_url_env mismatch" in warning for warning in warnings)


def test_ablation_main_result_summarizes_full_soe_headlines() -> None:
    main_result = _ablation_main_result(
        {"full_soe": {"Num-Tuples": 164, "Tuple-F1-semantic@0.3": 0.6272}}
    )

    assert main_result == {
        "setting": "full_soe",
        "tuples": 164,
        "f1_semantic_03": 0.6272,
    }


def test_main_configs_use_soe_v3_coverage_optimized() -> None:
    paper = load_config("configs/paper.yaml")
    ablation = load_config("configs/ablation.yaml")

    assert paper.data["gold_tuples_path"] == "data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl"
    assert paper.data["gold_event_chains_path"] == "data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl"
    assert paper.output["runs_dir"] == "outputs/runs_human_gold_v2"
    assert ablation.data["gold_tuples_path"] == "data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl"
    assert ablation.data["gold_event_chains_path"] == "data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl"
    assert ablation.output["runs_dir"] == "outputs/runs_human_gold_v2"
    assert paper.ablation["method_version"] == "soe_v3"
    assert paper.ablation["evidence_selector"]["mode"] == "coverage_optimized"
    assert paper.ablation["max_evidence_per_event"] == 24
    assert ablation.ablation["method_version"] == "soe_v3"
    assert ablation.ablation["evidence_selector"]["mode"] == "coverage_optimized"


def test_full_soe_v3_and_without_soe_graph_ablation_flags() -> None:
    full_soe = ABLATION_SETTINGS["full_soe"]
    full_soe_high_recall = ABLATION_SETTINGS["full_soe_high_recall"]
    without_soe_graph = ABLATION_SETTINGS["without_soe_graph"]

    assert full_soe["method_version"] == "soe_v3"
    assert full_soe["selector_mode"] == "coverage_optimized"
    assert full_soe["use_graph"] is True
    assert full_soe["use_event_chain"] is True
    assert full_soe["use_soe_graph"] is True
    assert full_soe["use_stage_attribution"] is True
    assert full_soe["use_event_level_safety_net"] is True
    assert full_soe["use_hybrid_refinement"] is True
    assert full_soe["use_verifier_quality_gate"] is True
    assert full_soe["verifier_mode"] == "decomposed"
    assert full_soe_high_recall["method_version"] == "soe_v3"
    assert full_soe_high_recall["max_evidence_per_event"] == 60
    assert full_soe_high_recall["use_graph"] is True
    assert full_soe_high_recall["use_soe_graph"] is True
    assert full_soe_high_recall["use_stage_attribution"] is True
    assert full_soe_high_recall["use_event_level_safety_net"] is True
    assert full_soe_high_recall["use_hybrid_refinement"] is True
    assert full_soe_high_recall["use_verifier_quality_gate"] is True
    without_decomposed_verifier = ABLATION_SETTINGS["without_decomposed_verifier"]
    assert without_decomposed_verifier["use_graph"] is True
    assert without_decomposed_verifier["use_soe_graph"] is True
    assert without_decomposed_verifier["use_stage_attribution"] is True
    assert without_decomposed_verifier["use_event_level_safety_net"] is True
    assert without_decomposed_verifier["use_hybrid_refinement"] is True
    assert without_decomposed_verifier["verifier_mode"] == "id_only"
    assert without_decomposed_verifier["use_verifier_quality_gate"] is False
    assert without_soe_graph["method_version"] == "soe_v3"
    assert without_soe_graph["selector_mode"] == "coverage_optimized"
    assert without_soe_graph != full_soe
    assert without_soe_graph["use_graph"] is False
    assert without_soe_graph["use_event_chain"] is True
    assert without_soe_graph["use_soe_graph"] is False
    assert without_soe_graph["use_stage_attribution"] is True
    assert without_soe_graph["use_event_level_safety_net"] is True
    assert without_soe_graph["use_hybrid_refinement"] is True
    assert without_soe_graph["use_verifier_quality_gate"] is True
    assert "use_stage_attribution" in PIPELINE_FLAG_KEYS
    assert "use_event_level_safety_net" in PIPELINE_FLAG_KEYS
    assert "use_hybrid_refinement" in PIPELINE_FLAG_KEYS
    assert "use_verifier_quality_gate" in PIPELINE_FLAG_KEYS
    assert "max_evidence_per_event" in PIPELINE_FLAG_KEYS


def test_verifier_quality_gate_keeps_only_verified_predictions() -> None:
    supported = prediction("supported", verified=True, score=0.95)
    partial = prediction("partially_supported", verified=False, score=0.5)
    insufficient = prediction("insufficient_evidence", verified=False, score=0.0)

    kept, summary = _apply_verifier_quality_gate([supported, partial, insufficient], enabled=True)

    assert kept == [supported]
    assert summary == {
        "verifier_quality_gate_enabled": True,
        "num_before_quality_gate": 3,
        "num_after_quality_gate": 1,
        "num_removed_by_quality_gate": 2,
    }


def test_verifier_quality_gate_is_opt_in() -> None:
    supported = prediction("supported", verified=True, score=0.95)
    partial = prediction("partially_supported", verified=False, score=0.5)

    kept, summary = _apply_verifier_quality_gate([supported, partial], enabled=False)

    assert kept == [supported, partial]
    assert summary["verifier_quality_gate_enabled"] is False
    assert summary["num_removed_by_quality_gate"] == 0


def prediction(label: str, *, verified: bool, score: float) -> PredictionTuple:
    return PredictionTuple(
        event_id="E1",
        stakeholder="Residents",
        opinion="complain about safety",
        sentiment="negative",
        rationale="Residents complain",
        evidence_ids=["ev1"],
        support_label=label,
        support_score=score,
        verified=verified,
    )
