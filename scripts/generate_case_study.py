"""CLI entrypoint for EpiSOA case-study generation."""

from __future__ import annotations

import argparse

from episoa.evaluation.case_study import resolve_run_dir, write_case_study_examples


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate case_study_examples.json for an EpiSOA run.")
    parser.add_argument("--run-dir", "--run_dir", dest="run_dir", help="Run directory. Defaults to outputs/latest_run.txt.")
    parser.add_argument("--gold-tuples", default="data/pubevent_soa_lite/gold_tuples.jsonl")
    parser.add_argument("--max-cases", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_path = write_case_study_examples(
        resolve_run_dir(args.run_dir),
        gold_tuples_path=args.gold_tuples,
        max_cases=args.max_cases,
    )
    print(f"wrote case study examples to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
