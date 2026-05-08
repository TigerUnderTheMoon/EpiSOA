"""Print gold tuple samples for manual inspection."""

from __future__ import annotations

import argparse

from episoa.annotation.gold_annotation import inspect_gold_samples


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(
        inspect_gold_samples(
            gold_tuples_path=args.gold_tuples,
            evidence_path=args.evidence,
            event_id=args.event_id,
            limit=args.limit,
            show_evidence=args.show_evidence,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect gold tuple samples.")
    parser.add_argument("--gold-tuples", default="outputs/runs/gold_annotation/gold_export/gold_tuples.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_filtered.jsonl")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--show-evidence", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())

