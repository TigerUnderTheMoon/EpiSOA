import subprocess
import sys


def test_cli_exposes_file_based_pipeline_commands() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "episoa.cli", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "collect-evidence" in completed.stdout
    assert "normalize-evidence" in completed.stdout
    assert "retrieve-paths" in completed.stdout
    assert "verify-tuples" in completed.stdout
    assert "paper-status" in completed.stdout


def test_cli_collect_evidence_fails_clearly_when_input_missing(tmp_path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "episoa.cli", "collect-evidence"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "required input file not found" in completed.stderr


def test_cli_exposes_formal_dataset_commands() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "episoa.cli", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "init-formal-dataset" in completed.stdout
    assert "validate-formal-dataset" in completed.stdout
