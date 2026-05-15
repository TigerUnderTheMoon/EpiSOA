"""Command line interface for the EpiSOA paper workflow."""

from __future__ import annotations

import argparse
import json

from episoa.pipeline import paper_status, run_ablation_pipeline, run_paper_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EpiSOA reproducible paper workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("paper-status")
    status.set_defaults(handler=_paper_status)

    run = subparsers.add_parser("run-paper")
    run.add_argument("--config", default="configs/paper.yaml")
    run.set_defaults(handler=_run_paper)

    ablation = subparsers.add_parser("run-ablation")
    ablation.add_argument("--config", default="configs/ablation.yaml")
    ablation.add_argument("--force", action="store_true",
                          help="Remove existing setting directories before re-running all settings")
    ablation.set_defaults(handler=_run_ablation)
    return parser


def _paper_status(args: argparse.Namespace) -> int:
    del args
    print(json.dumps(paper_status(), ensure_ascii=False, indent=2))
    return 0


def _run_paper(args: argparse.Namespace) -> int:
    result = run_paper_pipeline(args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_ablation(args: argparse.Namespace) -> int:
    result = run_ablation_pipeline(args.config, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
