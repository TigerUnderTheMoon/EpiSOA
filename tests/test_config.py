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
