"""Spec-aligned command line interface for EpiSOA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from episoa.config import ExperimentConfig, load_experiment_config
from episoa import experimental_pipeline as file_pipeline
from episoa.pipeline import PipelineResult, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA paper experiment workflows.")
    subparsers = parser.add_subparsers(dest="command")

    _add_config_command(subparsers, "collect", "Run configured collection through the pipeline.")
    _add_config_command(subparsers, "normalize", "Run configured normalization through the pipeline.")
    _add_file_command(subparsers, "build-graph", _build_graph_files, "Build SEEG nodes and edges from normalized evidence.")
    _add_config_command(subparsers, "retrieve", "Run configured event-chain retrieval through the pipeline.")
    _add_config_command(subparsers, "attribute", "Run configured tuple attribution through the pipeline.")
    _add_config_command(subparsers, "verify", "Run configured verification through the pipeline.")
    _add_config_command(subparsers, "run-all", "Run the full configured EpiSOA workflow.")

    _add_file_command(subparsers, "collect-evidence", _collect_evidence, "Collect smoke evidence from event queries.")
    _add_file_command(subparsers, "normalize-evidence", _normalize_evidence, "Normalize collected evidence.")
    _add_file_command(subparsers, "retrieve-paths", _retrieve_paths, "Retrieve event paths from SEEG graph files.")
    _add_file_command(subparsers, "generate-tuples", _generate_tuples, "Generate candidate SOA tuples.")
    _add_file_command(subparsers, "verify-tuples", _verify_tuples, "Verify candidate SOA tuples.")

    baselines = _add_config_command(subparsers, "run-baselines", "Run configured baselines.")
    baselines.set_defaults(handler=_run_baselines)

    ablation = _add_config_command(subparsers, "run-ablation", "Run configured ablations.")
    ablation.set_defaults(handler=_run_ablation)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate verified SOA tuples against smoke-test gold tuples.")
    evaluate.add_argument("--runs-dir", default=None, help="Optional legacy run-artifact directory for paper export.")
    evaluate.add_argument("--output", default=None, help="Optional legacy paper export directory.")
    evaluate.set_defaults(handler=_export_results)

    export_results = subparsers.add_parser("export-results", help="Export paper result tables from run artifacts.")
    export_results.add_argument("--runs-dir", default="outputs/runs")
    export_results.add_argument("--output", default="results")
    export_results.set_defaults(handler=_export_results)

    readiness = subparsers.add_parser("paper-status", help="Check formal dataset and paper-result readiness.")
    readiness.add_argument("--output", default="outputs/paper_readiness_report.json")
    readiness.set_defaults(handler=_paper_status)

    init_formal = subparsers.add_parser("init-formal-dataset", help="Create empty formal dataset files and annotation CSV.")
    init_formal.set_defaults(handler=_init_formal_dataset)

    validate_formal = subparsers.add_parser("validate-formal-dataset", help="Validate the formal dataset gate files.")
    validate_formal.set_defaults(handler=_validate_formal_dataset)

    init = subparsers.add_parser("init", help="Create canonical data/results directories.")
    init.set_defaults(handler=_init_project)

    parser.set_defaults(handler=_run_full_pipeline, config="configs/default.yaml")
    return parser


def _add_config_command(subparsers: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    command = subparsers.add_parser(name, help=help_text)
    command.add_argument("--config", default="configs/default.yaml", help="Experiment YAML config.")
    command.set_defaults(handler=_run_full_pipeline)
    return command


def _add_file_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    handler: Callable[[argparse.Namespace], int],
    help_text: str,
) -> argparse.ArgumentParser:
    command = subparsers.add_parser(name, help=help_text)
    command.set_defaults(handler=handler)
    return command


def _run_full_pipeline(args: argparse.Namespace) -> int:
    result = run_pipeline(load_experiment_config(args.config))
    _print_result(result)
    return 0


def _run_baselines(args: argparse.Namespace) -> int:
    from scripts.run_baselines import run_baselines

    outputs = run_baselines(load_experiment_config(args.config))
    print(json.dumps(outputs, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_ablation(args: argparse.Namespace) -> int:
    from scripts.run_ablations import run_ablations

    outputs = run_ablations(load_experiment_config(args.config))
    print(json.dumps(outputs, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _collect_evidence(args: argparse.Namespace) -> int:
    del args
    count = file_pipeline.collect_evidence()
    print(json.dumps({"input": "data/event_queries.jsonl", "output": "data/coverage_aware_evidence_pool.jsonl", "records": count}, indent=2))
    return 0


def _normalize_evidence(args: argparse.Namespace) -> int:
    del args
    count = file_pipeline.normalize_evidence()
    print(json.dumps({"input": "data/coverage_aware_evidence_pool.jsonl", "output": "data/normalized_evidence.jsonl", "records": count}, indent=2))
    return 0


def _retrieve_paths(args: argparse.Namespace) -> int:
    del args
    count = file_pipeline.retrieve_paths()
    print(json.dumps({"inputs": ["data/seeg_nodes.jsonl", "data/seeg_edges.jsonl"], "output": "data/event_paths.jsonl", "records": count}, indent=2))
    return 0


def _generate_tuples(args: argparse.Namespace) -> int:
    del args
    count = file_pipeline.generate_tuples()
    print(json.dumps({"inputs": ["data/event_paths.jsonl", "data/normalized_evidence.jsonl"], "output": "data/candidate_soa_tuples.jsonl", "records": count}, indent=2))
    return 0


def _verify_tuples(args: argparse.Namespace) -> int:
    del args
    count = file_pipeline.verify_tuples()
    print(json.dumps({"inputs": ["data/candidate_soa_tuples.jsonl", "data/normalized_evidence.jsonl"], "output": "data/verified_soa_tuples.jsonl", "records": count}, indent=2))
    return 0


def _build_graph_files(args: argparse.Namespace) -> int:
    del args
    nodes, edges = file_pipeline.build_graph()
    print(json.dumps({"input": "data/normalized_evidence.jsonl", "outputs": ["data/seeg_nodes.jsonl", "data/seeg_edges.jsonl"], "nodes": nodes, "edges": edges}, indent=2))
    return 0


def _export_results(args: argparse.Namespace) -> int:
    if not getattr(args, "runs_dir", None):
        metrics = file_pipeline.evaluate_outputs()
        print(
            json.dumps(
                {
                    "inputs": ["data/gold_soa_tuples.jsonl", "data/verified_soa_tuples.jsonl"],
                    "outputs": ["results/main_results.csv", "results/ablation_results.csv"],
                    "metrics": metrics,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    from scripts.export_paper_tables import export_paper_tables

    paths = export_paper_tables(args.runs_dir, args.output or "results")
    print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _paper_status(args: argparse.Namespace) -> int:
    from scripts.check_paper_readiness import build_readiness_report

    report = build_readiness_report()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _init_formal_dataset(args: argparse.Namespace) -> int:
    del args
    from scripts.build_annotation_sheet import FIELDNAMES

    dataset_dir = Path("data/pubevent_soa_formal")
    dataset_dir.mkdir(parents=True, exist_ok=True)
    formal_files = [
        dataset_dir / "events.jsonl",
        dataset_dir / "evidence.jsonl",
        dataset_dir / "gold_tuples.jsonl",
        dataset_dir / "gold_event_chains.jsonl",
    ]
    created: list[str] = []
    preserved: list[str] = []
    for path in formal_files:
        if path.exists():
            preserved.append(str(path))
        else:
            path.write_text("", encoding="utf-8")
            created.append(str(path))

    annotation_path = Path("outputs/annotation_sheet_formal.csv")
    annotation_path.parent.mkdir(parents=True, exist_ok=True)
    if annotation_path.exists():
        preserved.append(str(annotation_path))
    else:
        annotation_path.write_text(",".join(FIELDNAMES) + "\n", encoding="utf-8")
        created.append(str(annotation_path))

    print(
        json.dumps(
            {
                "dataset_dir": str(dataset_dir),
                "created": created,
                "preserved_existing": preserved,
                "note": "No formal records were generated.",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _validate_formal_dataset(args: argparse.Namespace) -> int:
    del args
    from scripts.validate_dataset import validate_dataset

    report = validate_dataset(
        "data/pubevent_soa_formal/events.jsonl",
        "data/pubevent_soa_formal/evidence.jsonl",
        "data/pubevent_soa_formal/gold_tuples.jsonl",
        "data/pubevent_soa_formal/gold_event_chains.jsonl",
    )
    output_path = Path("outputs/dataset_validation_formal.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"wrote dataset validation report: {output_path}")
    return 1 if report["errors"] else 0


def _init_project(args: argparse.Namespace) -> int:
    del args
    for directory in [
        "data/raw_collections",
        "data/splits",
        "data/annotation",
        "outputs/runs",
        "results",
    ]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    print("initialized EpiSOA directories")
    return 0


def _print_result(result: PipelineResult) -> None:
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "predictions_path": str(result.predictions_path),
                "metrics_path": str(result.run_dir / "metrics.json"),
                "summary_path": str(result.report_path),
                "num_events": result.num_events,
                "num_predictions": result.num_predictions,
                "metrics": result.metrics,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
