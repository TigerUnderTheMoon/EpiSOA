"""Lightly fetch public URLs into PubEvent-SOA raw_posts.jsonl."""

from __future__ import annotations

import argparse
import json

from episoa.dataset_construction import light_crawl_urls


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch public URL text into raw_posts.jsonl.")
    parser.add_argument("--urls", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = light_crawl_urls(args.urls, args.output, timeout_seconds=args.timeout_seconds)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
