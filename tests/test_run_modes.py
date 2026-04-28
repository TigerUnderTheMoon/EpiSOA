import json

import pytest

from episoa.config import load_experiment_config
from episoa.pipeline import run_pipeline


def _test_config(run_id: str):
    config = load_experiment_config("configs/default.yaml")
    config.run_id = run_id
    config.output.run_dir = "outputs/test_tmp/run_modes/{run_id}"
    return config.resolve_output_run_dir()


def test_mock_mode_runs_and_marks_summary() -> None:
    config = _test_config("mock-mode-smoke")

    result = run_pipeline(config)

    summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "mock"
    assert summary["run_id"] == "mock-mode-smoke"


def test_real_mode_missing_api_key_fails_clearly(monkeypatch) -> None:
    config = load_experiment_config("configs/experiment_real_llm.yaml")
    config.run_id = "real-mode-missing-key"
    config.output.run_dir = "outputs/test_tmp/run_modes/{run_id}"
    config = config.resolve_output_run_dir()
    monkeypatch.delenv(config.model.api_key_env, raising=False)

    with pytest.raises(RuntimeError, match=f"real mode requires API key environment variable {config.model.api_key_env}"):
        run_pipeline(config)


def test_ablation_mode_can_disable_specified_modules() -> None:
    config = _test_config("ablation-disable-modules")
    config.mode = "ablation"
    config.ablation.disable_graph = True
    config.ablation.disable_event_chain = True
    config.ablation.disable_verifier = True

    runtime = config.to_runtime_dict()

    assert runtime["graph"]["enabled"] is False
    assert runtime["event_chain"]["enabled"] is False
    assert runtime["verifier"]["enabled"] is False
    assert runtime["ablation"]["use_evidence_graph"] is False
    assert runtime["ablation"]["use_event_chain_retriever"] is False
    assert runtime["ablation"]["use_verifier"] is False


def test_summary_records_disabled_modules() -> None:
    config = _test_config("ablation-summary-disabled")
    config.mode = "ablation"
    config.ablation.disable_diversity = True
    config.ablation.disable_temporal_edges = True
    config.ablation.disable_stakeholder_constraint = True

    result = run_pipeline(config)

    summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "ablation"
    assert summary["disabled_modules"] == [
        "disable_diversity",
        "disable_temporal_edges",
        "disable_stakeholder_constraint",
    ]
