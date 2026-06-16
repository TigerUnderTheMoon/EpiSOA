from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_run_ablation_entrypoint_prefers_local_src(tmp_path: Path) -> None:
    fake_root = tmp_path / "fakepkg"
    fake_episoa = fake_root / "episoa"
    fake_episoa.mkdir(parents=True)
    (fake_episoa / "__init__.py").write_text("", encoding="utf-8")
    (fake_episoa / "pipeline.py").write_text(
        "raise RuntimeError('imported fake episoa')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_root)

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_ablation.py"), "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "imported fake episoa" not in result.stderr


@pytest.mark.unit
def test_run_paper_experiment_entrypoint_prefers_local_src(tmp_path: Path) -> None:
    fake_root = tmp_path / "fakepkg"
    fake_episoa = fake_root / "episoa"
    fake_episoa.mkdir(parents=True)
    (fake_episoa / "__init__.py").write_text("", encoding="utf-8")
    (fake_episoa / "pipeline.py").write_text(
        "raise RuntimeError('imported fake episoa')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_root)

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_paper_experiment.py"), "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "imported fake episoa" not in result.stderr
