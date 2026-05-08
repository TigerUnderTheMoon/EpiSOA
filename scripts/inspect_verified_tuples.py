"""Inspect verified SOA tuple outputs."""

from __future__ import annotations

import argparse
from collections import Counter

from episoa.data.loader import read_jsonl


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = read_jsonl(args.verified)
    labels = Counter(row.get("verification_label", "unclear") for row in rows)
    flags = Counter(flag for row in rows for flag in row.get("issue_flags", []))
    print(f"num_rows: {len(rows)}")
    print(f"label_distribution: {dict(labels)}")
    print(f"issue_flag_distribution: {dict(flags)}")
    for row in rows[: args.limit]:
        print(
            f"{row.get('tuple_id')} {row.get('verification_label')} "
            f"{row.get('verification_score')} {row.get('issue_flags')} "
            f"{row.get('stakeholder')} | {row.get('opinion')}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect verified SOA tuples.")
    parser.add_argument("--verified", default="outputs/runs/faithfulness_verification/verified_soa_tuples.jsonl")
    parser.add_argument("--limit", type=int, default=20)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
