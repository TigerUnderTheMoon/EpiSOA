"""Generate silver attribution candidates from raw posts and events."""

from __future__ import annotations

import argparse
import json

from episoa.dataset_construction import generate_silver_tuples


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate LLM/rule silver tuples.")
    parser.add_argument("--raw-posts", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--llm-model", default="rule_based_silver")
    parser.add_argument("--prompt-version", default="urban-renewal-v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = generate_silver_tuples(
        args.raw_posts,
        args.events,
        args.output,
        llm_model=args.llm_model,
        prompt_version=args.prompt_version,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
