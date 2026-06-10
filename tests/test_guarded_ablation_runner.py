from pathlib import Path

import yaml

from scripts import run_guarded_ablation
from scripts.run_guarded_ablation import GuardedAblationRunner, api_canary


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'


class CapturingHttpxClient:
    last_json: dict | None = None
    last_url: str | None = None
    last_headers: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def post(self, url, *, headers, json):
        CapturingHttpxClient.last_url = url
        CapturingHttpxClient.last_headers = headers
        CapturingHttpxClient.last_json = json
        return FakeResponse()


def test_guarded_runner_stops_before_full_when_stage_gate_fails(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> int:
        calls.append(command)
        if any(part.endswith("check_result_targets.py") for part in command):
            return 1
        return 0

    runner = GuardedAblationRunner(
        python_executable="python",
        canary=lambda: (True, "ok"),
        run_command=fake_run,
        runs_dir=tmp_path / "runs",
        stage_config=tmp_path / "runs" / "ablation_stage_guard_check.yaml",
        full_config=write_full_config(tmp_path),
    )

    result = runner.run()

    assert result["status"] == "failed"
    assert result["failed_step"] == "stage_guard_gate"
    assert any("ablation_stage_guard_check.yaml" in part for part in flatten(calls))
    assert not any("configs/ablation.yaml" in part for part in flatten(calls))


def test_guarded_runner_stops_before_experiments_when_canary_fails(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    runner = GuardedAblationRunner(
        python_executable="python",
        canary=lambda: (False, "503 service_unavailable"),
        run_command=lambda command: calls.append(command) or 0,
        runs_dir=tmp_path / "runs",
        stage_config=tmp_path / "runs" / "ablation_stage_guard_check.yaml",
        full_config=write_full_config(tmp_path),
    )

    result = runner.run()

    assert result["status"] == "failed"
    assert result["failed_step"] == "api_canary"
    assert calls == []


def test_guarded_runner_runs_main_and_full_only_after_stage_gate_passes(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    full_config = write_full_config(tmp_path)
    main_config = write_main_config(tmp_path)
    runner = GuardedAblationRunner(
        python_executable="python",
        canary=lambda: (True, "ok"),
        run_command=lambda command: calls.append(command) or 0,
        runs_dir=tmp_path / "runs",
        stage_config=tmp_path / "runs" / "ablation_stage_guard_check.yaml",
        full_config=full_config,
        main_config=main_config,
    )

    result = runner.run()

    assert result["status"] == "completed"
    flattened = flatten(calls)
    assert any("ablation_stage_guard_check.yaml" in part for part in flattened)
    assert any(part.endswith("check_result_targets.py") for part in flattened)
    assert any(part.endswith("run_paper_experiment.py") for part in flattened)
    assert any(part.endswith("build_main_vs_ablation_comparison.py") for part in flattened)
    assert any(part.replace("\\", "/") == str(full_config).replace("\\", "/") for part in flattened)
    assert calls[-1][1].endswith("check_result_targets.py")
    assert calls[-1][5] == "final"


def test_guarded_runner_reports_final_gate_failure_after_full_run(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> int:
        calls.append(command)
        if any(part.endswith("check_result_targets.py") for part in command) and "final" in command:
            return 1
        return 0

    runner = GuardedAblationRunner(
        python_executable="python",
        canary=lambda: (True, "ok"),
        run_command=fake_run,
        runs_dir=tmp_path / "runs",
        stage_config=tmp_path / "runs" / "ablation_stage_guard_check.yaml",
        full_config=write_full_config(tmp_path),
        main_config=write_main_config(tmp_path),
    )

    result = runner.run()

    assert result["status"] == "failed"
    assert result["failed_step"] == "final_result_gate"
    flattened = flatten(calls)
    assert any(part.endswith("run_paper_experiment.py") for part in flattened)
    assert any(part.endswith("run_ablation.py") for part in flattened)
    assert any(part.endswith("build_main_vs_ablation_comparison.py") for part in flattened)


def test_guarded_runner_stops_when_comparison_generation_fails(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> int:
        calls.append(command)
        if any(part.endswith("build_main_vs_ablation_comparison.py") for part in command):
            return 1
        return 0

    runner = GuardedAblationRunner(
        python_executable="python",
        canary=lambda: (True, "ok"),
        run_command=fake_run,
        runs_dir=tmp_path / "runs",
        stage_config=tmp_path / "runs" / "ablation_stage_guard_check.yaml",
        full_config=write_full_config(tmp_path),
        main_config=write_main_config(tmp_path),
    )

    result = runner.run()

    assert result["status"] == "failed"
    assert result["failed_step"] == "comparison_generation"
    flattened = flatten(calls)
    assert any(part.endswith("build_main_vs_ablation_comparison.py") for part in flattened)
    assert calls[-1][1].endswith("build_main_vs_ablation_comparison.py")


def test_api_canary_uses_model_and_base_url_from_config(tmp_path: Path, monkeypatch) -> None:
    config = write_model_config(tmp_path, model_name="configured-model", base_url="https://yaml.example/v1")
    monkeypatch.setattr(run_guarded_ablation.httpx, "Client", CapturingHttpxClient)

    ok, message = api_canary(config)

    assert ok is True
    assert message == "canary_ok"
    assert CapturingHttpxClient.last_url == "https://yaml.example/v1/chat/completions"
    assert CapturingHttpxClient.last_json["model"] == "configured-model"
    assert CapturingHttpxClient.last_headers["Authorization"] == "Bearer yaml-key"


def flatten(calls: list[list[str]]) -> list[str]:
    return [part for command in calls for part in command]


def write_full_config(tmp_path: Path) -> Path:
    path = tmp_path / "ablation.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "ablation": {"settings": ["full_soe", "without_soe_graph", "direct_llm"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def write_main_config(tmp_path: Path) -> Path:
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump({"run_id": "paper"}, sort_keys=False), encoding="utf-8")
    return path


def write_model_config(tmp_path: Path, *, model_name: str, base_url: str) -> Path:
    path = tmp_path / "paper_model.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "model": {
                    "llm_model": model_name,
                    "api_key": "yaml-key",
                    "base_url": base_url,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path
