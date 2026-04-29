import json
from pathlib import Path

from episoa.config import load_experiment_config
from episoa.pipeline import PipelineResult, run_pipeline


def test_unified_pipeline_smoke_generates_core_artifacts() -> None:
    config = load_experiment_config("configs/default.yaml")
    config.run_id = "pipeline-smoke"
    config.output.run_dir = "outputs/test_tmp/pipeline_smoke/{run_id}"
    config = config.resolve_output_run_dir()

    result = run_pipeline(config)

    assert isinstance(result, PipelineResult)
    assert result.run_id == "pipeline-smoke"
    assert result.num_events >= 1
    assert result.num_predictions >= 1
    assert result.predictions_path.exists()
    assert result.config_path.exists()
    assert (result.run_dir / "metrics.json").exists()
    assert (result.run_dir / "summary.json").exists()
    assert (result.run_dir / "collector_coverage.json").exists()
    assert (result.run_dir / "selected_evidence.jsonl").exists()
    assert (result.run_dir / "graph_summary.json").exists()
    assert (result.run_dir / "event_chain_candidates.jsonl").exists()
    assert (result.run_dir / "verification_report.json").exists()

    summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "pipeline-smoke"
    assert summary["num_predictions"] == result.num_predictions

    metrics = json.loads((result.run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert "opinion_f1" in metrics
    assert "temporal_order_accuracy" in metrics
