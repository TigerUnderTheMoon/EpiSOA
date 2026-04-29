import pytest
from pydantic import ValidationError

from episoa.config import ExperimentConfig, load_experiment_config, load_runtime_config


def test_default_yaml_loads_as_experiment_config() -> None:
    config = load_experiment_config("configs/default.yaml")

    assert config.seed == 13
    assert config.run_id == "pubevent-soa-lite-mock"
    assert config.mode == "mock"
    assert config.data.dataset_name == "pubevent_soa_lite"


def test_missing_required_fields_raise_clear_error() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ExperimentConfig.model_validate({"seed": 1, "run_id": "bad", "mode": "mock"})

    message = str(excinfo.value)
    assert "data" in message
    assert "model" in message
    assert "retrieval" in message


def test_seed_top_k_threshold_and_run_id_are_read() -> None:
    config = load_experiment_config("configs/default.yaml")

    assert config.seed == 13
    assert config.retrieval.top_k == 5
    assert config.verifier.threshold == 0.75
    assert config.run_id == "pubevent-soa-lite-mock"


def test_output_run_dir_resolves_from_run_id() -> None:
    config = load_experiment_config("configs/default.yaml")

    assert config.output.run_dir == "outputs/runs/pubevent-soa-lite-mock"


def test_runtime_config_keeps_existing_pipeline_compatibility() -> None:
    runtime = load_runtime_config("configs/default.yaml")

    assert runtime["pipeline"]["top_k_evidence"] == 5
    assert runtime["pipeline"]["eventrag_depth"] == 2
    assert runtime["verifier"]["threshold"] == 0.75
    assert runtime["output"]["run_dir"] == "outputs/runs/pubevent-soa-lite-mock"


def test_formal_configs_load_with_collector_defaults() -> None:
    formal = load_experiment_config("configs/formal.yaml")
    formal_ablation = load_experiment_config("configs/formal_ablation.yaml")

    assert formal.mode == "real"
    assert formal.data.require_formal_validation is True
    assert formal.collector.coverage_weights["traceability"] == 1.0
    assert formal_ablation.ablation_settings["without_temporal_edges"].disable_temporal_edges is True


def test_formal_validation_report_must_pass_before_real_run(tmp_path, monkeypatch) -> None:
    report = tmp_path / "dataset_validation_formal.json"
    report.write_text(
        '{"is_formal_dataset": false, "num_events": 0, "num_evidence": 0, '
        '"num_gold_tuples": 0, "num_gold_event_chains": 0, "errors": []}\n',
        encoding="utf-8",
    )
    config = load_experiment_config("configs/formal.yaml")
    config.data.validation_report_path = str(report)
    monkeypatch.setenv(config.model.api_key_env, "test-key")

    with pytest.raises(RuntimeError, match="is_formal_dataset=true"):
        config.validate_mode_requirements()
