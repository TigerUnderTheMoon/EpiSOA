"""Extract urban-renewal events from raw_posts.jsonl."""

from __future__ import annotations

import argparse
import json

from episoa.dataset_construction import extract_events


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract events from raw_posts.jsonl.")
    parser.add_argument("--raw-posts", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = extract_events(args.raw_posts, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
