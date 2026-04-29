"""Spec-aligned command line interface for EpiSOA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from episoa.config import ExperimentConfig, load_experiment_config
from episoa.pipeline import PipelineResult, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EpiSOA paper experiment workflows.")
    subparsers = parser.add_subparsers(dest="command")

    _add_config_command(subparsers, "collect", "Run configured collection through the pipeline.")
    _add_config_command(subparsers, "normalize", "Run configured normalization through the pipeline.")
    _add_config_command(subparsers, "build-graph", "Run configured graph construction through the pipeline.")
    _add_config_command(subparsers, "retrieve", "Run configured event-chain retrieval through the pipeline.")
    _add_config_command(subparsers, "attribute", "Run configured tuple attribution through the pipeline.")
    _add_config_command(subparsers, "verify", "Run configured verification through the pipeline.")
    _add_config_command(subparsers, "run-all", "Run the full configured EpiSOA workflow.")

    baselines = _add_config_command(subparsers, "run-baselines", "Run configured baselines.")
    baselines.set_defaults(handler=_run_baselines)

    ablation = _add_config_command(subparsers, "run-ablation", "Run configured ablations.")
    ablation.set_defaults(handler=_run_ablation)

    evaluate = subparsers.add_parser("evaluate", help="Export paper result tables from run artifacts.")
    evaluate.add_argument("--runs-dir", default="outputs/runs")
    evaluate.add_argument("--output", default="results")
    evaluate.set_defaults(handler=_export_results)

    export_results = subparsers.add_parser("export-results", help="Alias for evaluate.")
    export_results.add_argument("--runs-dir", default="outputs/runs")
    export_results.add_argument("--output", default="results")
    export_results.set_defaults(handler=_export_results)

    init = subparsers.add_parser("init", help="Create canonical data/results directories.")
    init.set_defaults(handler=_init_project)

    parser.set_defaults(handler=_run_full_pipeline, config="configs/default.yaml")
    return parser


def _add_config_command(subparsers: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    command = subparsers.add_parser(name, help=help_text)
    command.add_argument("--config", default="configs/default.yaml", help="Experiment YAML config.")
    command.set_defaults(handler=_run_full_pipeline)
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


def _export_results(args: argparse.Namespace) -> int:
    from scripts.export_paper_tables import export_paper_tables

    paths = export_paper_tables(args.runs_dir, args.output)
    print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


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
