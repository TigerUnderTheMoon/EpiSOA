"""Import public-text exports into PubEvent-SOA raw_posts.jsonl."""

from __future__ import annotations

import argparse
import json

from episoa.dataset_construction import import_raw_posts


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import CSV/JSONL exports into raw_posts.jsonl.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = import_raw_posts(args.input, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
