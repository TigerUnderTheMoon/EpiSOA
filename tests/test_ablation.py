import json
import importlib.util
from pathlib import Path

import pytest


def load_run_ablation_module():
    module_path = Path("scripts/run_ablation.py")
    spec = importlib.util.spec_from_file_location("run_ablation", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_run_ablation_setting_writes_predictions_and_metrics() -> None:
    run_ablation = load_run_ablation_module()
    config = run_ablation.load_config("configs/ablation.yaml")
    run_dir = Path("outputs/test_ablation_run").resolve()

    prediction_path, metrics_path = run_ablation.run_ablation_setting(
        config,
        "w/o_verifier",
        run_dir=run_dir,
    )

    assert prediction_path.exists()
    assert metrics_path.exists()
    assert prediction_path.parent == run_dir / "predictions" / "ablations"
    assert metrics_path.parent == run_dir / "metrics" / "ablations"
    assert prediction_path.read_text(encoding="utf-8").strip()

    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    assert "stakeholder_f1" in metrics
    assert "unsupported_tuple_rate" in metrics


@pytest.mark.integration
def test_run_ablations_uses_latest_run_and_writes_root_summary_csv() -> None:
    run_ablation = load_run_ablation_module()
    config = run_ablation.load_config("configs/ablation.yaml")
    config["settings"] = {
        "full_model": config["settings"]["full_model"],
        "w/o_verifier": config["settings"]["w/o_verifier"],
    }
    run_dir = Path("outputs/test_ablation_latest_run").resolve()
    latest_path = Path("outputs/latest_run.txt")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(str(run_dir.resolve()), encoding="utf-8")
    root_config_path = run_dir / "config.yaml"
    root_config_path.parent.mkdir(parents=True, exist_ok=True)
    root_config_path.write_text("run:\n  run_id: existing\n", encoding="utf-8")

    outputs = run_ablation.run_ablations(config, "all")
    summary_path = run_dir / "ablation_summary.csv"

    assert set(outputs) == {"full_model", "w/o_verifier"}
    assert summary_path.exists()
    assert (run_dir / "run.log").exists()
    assert root_config_path.read_text(encoding="utf-8") == "run:\n  run_id: existing\n"
    text = summary_path.read_text(encoding="utf-8")
    assert "setting" in text
    assert "full_model" in text
    assert "w/o_verifier" in text

    for paths in outputs.values():
        prediction_path = Path(paths["prediction_path"])
        metrics_path = Path(paths["metrics_path"])
        assert prediction_path.exists()
        assert metrics_path.exists()
        assert prediction_path.parent == run_dir / "predictions" / "ablations"
        assert metrics_path.parent == run_dir / "metrics" / "ablations"
