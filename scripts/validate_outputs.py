"""Validate required paper-output artifacts for an EpiSOA run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FILES = [
    "summary_table.csv",
    "ablation_summary.csv",
    "error_analysis.jsonl",
    "case_study_examples.json",
]


def resolve_run_dir(run_dir: str | Path | None = None) -> Path:
    """Resolve an explicit run directory or the latest run pointer."""
    if run_dir is not None:
        return Path(run_dir)
    latest_path = Path("outputs/latest_run.txt")
    if not latest_path.exists():
        raise FileNotFoundError("outputs/latest_run.txt not found; pass --run-dir explicitly")
    return Path(latest_path.read_text(encoding="utf-8").strip())


def validate_run_outputs(run_dir: str | Path | None = None) -> dict[str, bool]:
    """Return file-presence status and validate case-study JSON shape."""
    resolved_run_dir = resolve_run_dir(run_dir)
    status = {name: (resolved_run_dir / name).exists() for name in REQUIRED_FILES}
    missing = [name for name, exists in status.items() if not exists]
    if missing:
        raise FileNotFoundError(f"Missing required output files in {resolved_run_dir}: {', '.join(missing)}")

    payload = json.loads((resolved_run_dir / "case_study_examples.json").read_text(encoding="utf-8"))
    if not isinstance(payload.get("description"), str):
        raise ValueError("case_study_examples.json must include string description")
    if not isinstance(payload.get("num_cases"), int):
        raise ValueError("case_study_examples.json must include integer num_cases")
    if not isinstance(payload.get("cases"), list):
        raise ValueError("case_study_examples.json must include list cases")
    required_case_fields = {
        "case_id",
        "case_type",
        "input_text",
        "gold_label",
        "prediction",
        "analysis",
        "source",
    }
    for index, case in enumerate(payload["cases"], start=1):
        missing_fields = required_case_fields - set(case)
        if missing_fields:
            raise ValueError(f"case {index} missing fields: {', '.join(sorted(missing_fields))}")
    return status


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate EpiSOA paper-output files.")
    parser.add_argument("--run-dir", help="Run directory. Defaults to outputs/latest_run.txt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    run_dir = resolve_run_dir(args.run_dir)
    status = validate_run_outputs(run_dir)
    for name, exists in status.items():
        print(f"{name}: {'OK' if exists else 'MISSING'}")
    print(f"validated run_dir: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
