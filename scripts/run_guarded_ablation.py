"""Run ablation only after a two-setting improvement gate passes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

import httpx
import yaml

from episoa.config import load_config, resolve_api_config


CommandRunner = Callable[[list[str]], int]
Canary = Callable[[], tuple[bool, str]]


class GuardedAblationRunner:
    def __init__(
        self,
        *,
        python_executable: str,
        canary: Canary | None = None,
        run_command: CommandRunner | None = None,
        runs_dir: str | Path = "outputs/runs_human_gold_v2",
        stage_config: str | Path = "outputs/runs_human_gold_v2/ablation_stage_guard_check.yaml",
        full_config: str | Path = "configs/ablation.yaml",
        main_config: str | Path = "configs/paper.yaml",
    ) -> None:
        self.python_executable = python_executable
        self.canary = canary or api_canary
        self.run_command = run_command or _run_subprocess
        self.runs_dir = Path(runs_dir)
        self.stage_config = Path(stage_config)
        self.full_config = Path(full_config)
        self.main_config = Path(main_config)

    def run(self) -> dict[str, object]:
        ok, message = self.canary()
        if not ok:
            return self._failed("api_canary", message)

        self._write_stage_guard_config()
        stage_command = [
            self.python_executable,
            "scripts/run_ablation.py",
            "--config",
            str(self.stage_config),
            "--force",
        ]
        stage_code = self.run_command(stage_command)
        if stage_code != 0:
            return self._failed("two_setting_ablation", f"exit_code={stage_code}")

        gate_command = [
            self.python_executable,
            "scripts/check_result_targets.py",
            "--runs-dir",
            str(self.runs_dir),
            "--mode",
            "stage-guard",
        ]
        gate_code = self.run_command(gate_command)
        if gate_code != 0:
            return self._failed("stage_guard_gate", f"exit_code={gate_code}")

        main_command = [
            self.python_executable,
            "scripts/run_paper_experiment.py",
            "--config",
            str(self.main_config),
        ]
        main_code = self.run_command(main_command)
        if main_code != 0:
            return self._failed("main_experiment", f"exit_code={main_code}")

        full_command = [
            self.python_executable,
            "scripts/run_ablation.py",
            "--config",
            str(self.full_config),
            "--force",
        ]
        full_code = self.run_command(full_command)
        if full_code != 0:
            return self._failed("full_ablation", f"exit_code={full_code}")

        comparison_command = [
            self.python_executable,
            "scripts/build_main_vs_ablation_comparison.py",
            "--runs-dir",
            str(self.runs_dir),
        ]
        comparison_code = self.run_command(comparison_command)
        if comparison_code != 0:
            return self._failed("comparison_generation", f"exit_code={comparison_code}")

        final_gate_command = [
            self.python_executable,
            "scripts/check_result_targets.py",
            "--runs-dir",
            str(self.runs_dir),
            "--mode",
            "final",
        ]
        final_gate_code = self.run_command(final_gate_command)
        if final_gate_code != 0:
            return self._failed("final_result_gate", f"exit_code={final_gate_code}")

        return {"status": "completed", "failed_step": None, "message": "final_result_gate_passed"}

    def _write_stage_guard_config(self) -> None:
        source = yaml.safe_load(self.full_config.read_text(encoding="utf-8"))
        source.setdefault("ablation", {})["settings"] = ["full_soe", "without_soe_graph"]
        self.stage_config.parent.mkdir(parents=True, exist_ok=True)
        self.stage_config.write_text(
            yaml.safe_dump(source, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @staticmethod
    def _failed(step: str, message: str) -> dict[str, object]:
        return {"status": "failed", "failed_step": step, "message": message}


def api_canary(config_path: str | Path | None = None) -> tuple[bool, str]:
    if config_path is None:
        base_url = (os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        model_name = "gpt-5.5"
        if not base_url:
            return False, "OPENAI_BASE_URL is missing"
        if not api_key:
            return False, "OPENAI_API_KEY is missing"
    else:
        try:
            config = load_config(config_path)
            resolved = resolve_api_config(config.model, label="model")
        except Exception as exc:
            return False, str(exc)
        base_url = str(resolved["base_url"]).rstrip("/")
        api_key = str(resolved["api_key"])
        model_name = str(config.model.get("llm_model") or config.model.get("model_name") or "gpt-5.5")

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": '{"ok":true}'},
        ],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if response.status_code >= 400:
        return False, f"status_code={response.status_code}; {response.text[:500]}"
    return True, "canary_ok"


def _run_subprocess(command: list[str]) -> int:
    completed = subprocess.run(command)
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--runs-dir", default="outputs/runs_human_gold_v2")
    parser.add_argument("--stage-config", default="outputs/runs_human_gold_v2/ablation_stage_guard_check.yaml")
    parser.add_argument("--full-config", default="configs/ablation.yaml")
    parser.add_argument("--main-config", default="configs/paper.yaml")
    args = parser.parse_args()

    runner = GuardedAblationRunner(
        python_executable=args.python,
        runs_dir=args.runs_dir,
        stage_config=args.stage_config,
        full_config=args.full_config,
        main_config=args.main_config,
    )
    result = runner.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
