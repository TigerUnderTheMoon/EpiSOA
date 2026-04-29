"""Build annotation-ready candidate evidence pairs."""

from __future__ import annotations

import argparse
import json

from episoa.dataset_construction import build_evidence_pairs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build candidate evidence pairs from raw posts and silver tuples.")
    parser.add_argument("--raw-posts", required=True)
    parser.add_argument("--silver", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_evidence_pairs(args.raw_posts, args.silver, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
