"""CLI entrypoint for EpiSOA error analysis."""

from __future__ import annotations

import argparse

from episoa.evaluation.error_analysis import run_error_analysis


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate EpiSOA error analysis artifacts.")
    parser.add_argument("--run-dir", "--run_dir", dest="run_dir", help="Run directory. Defaults to outputs/latest_run.txt.")
    parser.add_argument("--gold-tuples", default="data/pubevent_soa_lite/gold_tuples.jsonl")
    parser.add_argument("--gold-event-chains", default="data/pubevent_soa_lite/gold_event_chains.jsonl")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    paths = run_error_analysis(
        args.run_dir,
        gold_tuples_path=args.gold_tuples,
        gold_event_chains_path=args.gold_event_chains,
    )
    print(f"wrote error analysis to {paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
