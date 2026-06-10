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
    _add_runtime_args(run, include_settings=False)
    run.set_defaults(handler=_run_paper)

    ablation = subparsers.add_parser("run-ablation")
    ablation.add_argument("--config", default="configs/ablation.yaml")
    ablation.add_argument("--force", action="store_true",
                          help="Remove existing setting directories before re-running all settings")
    _add_runtime_args(ablation, include_settings=True)
    ablation.set_defaults(handler=_run_ablation)
    return parser


def _add_runtime_args(parser: argparse.ArgumentParser, *, include_settings: bool) -> None:
    parser.add_argument("--resume", action="store_true", default=None)
    parser.add_argument("--max-api-concurrency", type=int, default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--diagnostic", action="store_true", default=None)
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--event-ids", default=None, help="Comma-separated event IDs for diagnostic runs")
    parser.add_argument("--skip-llm-verifier", action="store_true", default=None)
    if include_settings:
        parser.add_argument("--settings", default=None, help="Comma-separated ablation settings to run")


def _paper_status(args: argparse.Namespace) -> int:
    del args
    print(json.dumps(paper_status(), ensure_ascii=False, indent=2))
    return 0


def _run_paper(args: argparse.Namespace) -> int:
    result = run_paper_pipeline(
        args.config,
        resume=args.resume,
        max_api_concurrency=args.max_api_concurrency,
        cache_dir=args.cache_dir,
        diagnostic=args.diagnostic,
        max_events=args.max_events,
        event_ids=_split_csv(args.event_ids),
        skip_llm_verifier=args.skip_llm_verifier,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_ablation(args: argparse.Namespace) -> int:
    result = run_ablation_pipeline(
        args.config,
        force=args.force,
        resume=args.resume,
        max_api_concurrency=args.max_api_concurrency,
        cache_dir=args.cache_dir,
        diagnostic=args.diagnostic,
        max_events=args.max_events,
        event_ids=_split_csv(args.event_ids),
        settings=_split_csv(args.settings),
        skip_llm_verifier=args.skip_llm_verifier,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
