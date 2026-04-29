"""Report whether EpiSOA formal paper experiments are ready to run."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

try:
    from scripts.validate_dataset import validate_dataset
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location("validate_dataset", Path(__file__).with_name("validate_dataset.py"))
    if spec is None or spec.loader is None:
        raise
    validate_dataset_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate_dataset_module)
    validate_dataset = validate_dataset_module.validate_dataset


DEFAULT_COMMANDS = {
    "build_annotation_sheet": (
        "python scripts/build_annotation_sheet.py "
        "--events data/pubevent_soa_formal/events.jsonl "
        "--evidence data/pubevent_soa_formal/evidence.jsonl "
        "--output outputs/annotation_sheet_formal.csv"
    ),
    "convert_gold_tuples": (
        "python scripts/convert_annotation_csv_to_gold.py "
        "--input outputs/annotation_sheet_formal_filled.csv "
        "--output data/pubevent_soa_formal/gold_tuples.jsonl "
        "--validation-output outputs/dataset_validation_formal.json"
    ),
    "validate_dataset": (
        "python scripts/validate_dataset.py "
        "--events data/pubevent_soa_formal/events.jsonl "
        "--evidence data/pubevent_soa_formal/evidence.jsonl "
        "--gold-tuples data/pubevent_soa_formal/gold_tuples.jsonl "
        "--gold-event-chains data/pubevent_soa_formal/gold_event_chains.jsonl "
        "--output outputs/dataset_validation_formal.json"
    ),
    "run_main": "python -m episoa.cli run-all --config configs/formal.yaml",
    "run_baselines": "python -m episoa.cli run-baselines --config configs/formal_baselines.yaml",
    "run_ablation": "python -m episoa.cli run-ablation --config configs/formal_ablation.yaml",
    "export_results": "python -m episoa.cli export-results --runs-dir outputs/runs --output results",
}


def build_readiness_report(
    *,
    events_path: str | Path = "data/pubevent_soa_formal/events.jsonl",
    evidence_path: str | Path = "data/pubevent_soa_formal/evidence.jsonl",
    gold_tuples_path: str | Path = "data/pubevent_soa_formal/gold_tuples.jsonl",
    gold_event_chains_path: str | Path = "data/pubevent_soa_formal/gold_event_chains.jsonl",
    annotation_sheet_path: str | Path = "outputs/annotation_sheet_formal.csv",
    filled_annotation_sheet_path: str | Path = "outputs/annotation_sheet_formal_filled.csv",
    results_dir: str | Path = "results",
    api_key_env: str = "OPENAI_API_KEY",
) -> dict[str, Any]:
    dataset_report = validate_dataset(events_path, evidence_path, gold_tuples_path, gold_event_chains_path)
    api_key_available = bool(os.environ.get(api_key_env))
    missing_items = _missing_items(
        dataset_report=dataset_report,
        api_key_available=api_key_available,
        annotation_sheet_path=Path(annotation_sheet_path),
        filled_annotation_sheet_path=Path(filled_annotation_sheet_path),
    )
    real_experiments_can_run = bool(dataset_report["is_formal_dataset"] and api_key_available)
    paper_outputs = _paper_outputs(Path(results_dir))
    formal_dataset_empty = _formal_dataset_empty(dataset_report)
    smoke_results_present = _smoke_results_present(Path(results_dir))

    return {
        "status": "ready_for_real_experiments" if real_experiments_can_run else "blocked",
        "messages": _status_messages(
            formal_dataset_empty=formal_dataset_empty,
            real_experiments_can_run=real_experiments_can_run,
            smoke_results_present=smoke_results_present,
        ),
        "dataset": {
            "is_formal_dataset": dataset_report["is_formal_dataset"],
            "num_events": dataset_report["num_events"],
            "num_evidence": dataset_report["num_evidence"],
            "num_gold_tuples": dataset_report["num_gold_tuples"],
            "num_gold_event_chains": dataset_report["num_gold_event_chains"],
            "errors": dataset_report["errors"],
            "warnings": dataset_report["warnings"],
        },
        "environment": {
            "api_key_env": api_key_env,
            "api_key_available": api_key_available,
        },
        "artifacts": {
            "annotation_sheet_exists": Path(annotation_sheet_path).exists(),
            "filled_annotation_sheet_exists": Path(filled_annotation_sheet_path).exists(),
            "paper_outputs": paper_outputs,
            "smoke_results_present": smoke_results_present,
        },
        "missing_items": missing_items,
        "real_experiments_can_run": real_experiments_can_run,
        "next_commands": _next_commands(dataset_report, api_key_available),
    }


def _formal_dataset_empty(dataset_report: dict[str, Any]) -> bool:
    return all(
        dataset_report.get(key, 0) == 0
        for key in ("num_events", "num_evidence", "num_gold_tuples", "num_gold_event_chains")
    )


def _status_messages(
    *,
    formal_dataset_empty: bool,
    real_experiments_can_run: bool,
    smoke_results_present: bool,
) -> list[str]:
    messages: list[str] = []
    if formal_dataset_empty:
        messages.append("formal dataset is empty")
    if not real_experiments_can_run:
        messages.append("real experiments are blocked")
    if smoke_results_present:
        messages.append("current main_results.csv and ablation_results.csv are not formal results if generated from smoke-test data")
    return messages


def _missing_items(
    *,
    dataset_report: dict[str, Any],
    api_key_available: bool,
    annotation_sheet_path: Path,
    filled_annotation_sheet_path: Path,
) -> list[str]:
    missing: list[str] = []
    if dataset_report["num_events"] == 0:
        missing.append("Fill data/pubevent_soa_formal/events.jsonl with human-curated public events.")
    if dataset_report["num_evidence"] == 0:
        missing.append("Fill data/pubevent_soa_formal/evidence.jsonl with traceable public evidence.")
    if not annotation_sheet_path.exists():
        missing.append("Generate outputs/annotation_sheet_formal.csv from formal events and evidence.")
    if not filled_annotation_sheet_path.exists():
        missing.append("Complete human annotations in outputs/annotation_sheet_formal_filled.csv.")
    if dataset_report["num_gold_tuples"] == 0:
        missing.append("Convert human annotations into data/pubevent_soa_formal/gold_tuples.jsonl.")
    if dataset_report["num_gold_event_chains"] == 0:
        missing.append("Curate data/pubevent_soa_formal/gold_event_chains.jsonl.")
    if dataset_report["errors"]:
        missing.append("Fix dataset validation errors before any formal experiment.")
    if not dataset_report["is_formal_dataset"]:
        missing.append("Make validation report set is_formal_dataset=true.")
    if not api_key_available:
        missing.append("Set OPENAI_API_KEY before running real experiments.")
    return missing


def _paper_outputs(results_dir: Path) -> dict[str, bool]:
    return {
        "main_results.csv": (results_dir / "main_results.csv").exists(),
        "ablation_results.csv": (results_dir / "ablation_results.csv").exists(),
        "case_studies.jsonl": (results_dir / "case_studies.jsonl").exists(),
    }


def _smoke_results_present(results_dir: Path) -> bool:
    for filename in ("main_results.csv", "ablation_results.csv"):
        path = results_dir / filename
        if path.exists() and "smoke" in path.read_text(encoding="utf-8").lower():
            return True
    return False


def _next_commands(dataset_report: dict[str, Any], api_key_available: bool) -> list[str]:
    commands: list[str] = []
    if dataset_report["num_events"] > 0 and dataset_report["num_evidence"] > 0:
        commands.append(DEFAULT_COMMANDS["build_annotation_sheet"])
    if dataset_report["num_gold_tuples"] == 0:
        commands.append(DEFAULT_COMMANDS["convert_gold_tuples"])
    commands.append(DEFAULT_COMMANDS["validate_dataset"])
    if dataset_report["is_formal_dataset"] and api_key_available:
        commands.extend(
            [
                DEFAULT_COMMANDS["run_main"],
                DEFAULT_COMMANDS["run_baselines"],
                DEFAULT_COMMANDS["run_ablation"],
                DEFAULT_COMMANDS["export_results"],
            ]
        )
    return commands


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check EpiSOA paper experiment readiness.")
    parser.add_argument("--events", default="data/pubevent_soa_formal/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_formal/evidence.jsonl")
    parser.add_argument("--gold-tuples", default="data/pubevent_soa_formal/gold_tuples.jsonl")
    parser.add_argument("--gold-event-chains", default="data/pubevent_soa_formal/gold_event_chains.jsonl")
    parser.add_argument("--annotation-sheet", default="outputs/annotation_sheet_formal.csv")
    parser.add_argument("--filled-annotation-sheet", default="outputs/annotation_sheet_formal_filled.csv")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--output", default="outputs/paper_readiness_report.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_readiness_report(
        events_path=args.events,
        evidence_path=args.evidence,
        gold_tuples_path=args.gold_tuples,
        gold_event_chains_path=args.gold_event_chains,
        annotation_sheet_path=args.annotation_sheet,
        filled_annotation_sheet_path=args.filled_annotation_sheet,
        results_dir=args.results_dir,
        api_key_env=args.api_key_env,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote paper readiness report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
