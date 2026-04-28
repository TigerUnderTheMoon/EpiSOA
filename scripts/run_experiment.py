"""CLI entrypoint for the unified EpiSOA pipeline."""

from __future__ import annotations

import argparse
import json

from episoa.config import load_experiment_config
from episoa.pipeline import run_pipeline


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one configured EpiSOA pipeline experiment.")
    parser.add_argument("--config", default="configs/default.yaml", help="Experiment YAML config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_experiment_config(args.config)
    result = run_pipeline(config)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
