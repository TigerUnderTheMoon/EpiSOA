import importlib.util
from pathlib import Path


def load_script(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_experiment_cli_uses_unified_pipeline() -> None:
    work_dir = Path("outputs/test_tmp/run_experiment_cli")
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "default.yaml"
    config_path.write_text(
        Path("configs/default.yaml")
        .read_text(encoding="utf-8")
        .replace("run_id: pubevent-soa-lite-mock", "run_id: script-smoke")
        .replace("run_dir: outputs/runs/{run_id}", "run_dir: outputs/test_tmp/run_experiment_cli/runs/{run_id}"),
        encoding="utf-8",
    )
    module = load_script("scripts/run_experiment.py", "run_experiment")

    assert module.main(["--config", str(config_path)]) == 0

    run_dir = Path("outputs/test_tmp/run_experiment_cli/runs/script-smoke")
    assert (run_dir / "config.yaml").exists()
    assert (run_dir / "predictions.jsonl").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "summary.json").exists()


def test_run_real_llm_experiment_is_thin_pipeline_wrapper() -> None:
    module = load_script("scripts/run_real_llm_experiment.py", "run_real_llm_experiment")

    parser = module.build_arg_parser()
    args = parser.parse_args([])

    assert args.config == "configs/experiment_real_llm.yaml"


def test_spec_cli_exposes_run_all_and_export_commands() -> None:
    from episoa.cli import build_parser

    parser = build_parser()

    run_args = parser.parse_args(["run-all", "--config", "configs/default.yaml"])
    export_args = parser.parse_args(["evaluate", "--runs-dir", "outputs/runs", "--output", "results"])

    assert run_args.config == "configs/default.yaml"
    assert export_args.output == "results"
