"""Validate human-reviewed gold annotation outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from episoa.annotation.gold_annotation import validate_gold_dataset


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.gold_tuples).parent
    report = validate_gold_dataset(
        gold_tuples_path=args.gold_tuples,
        gold_event_chains_path=args.gold_event_chains,
        evidence_path=args.evidence,
        events_path=args.events,
        output_dir=output_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["hard_error_count"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate EpiSOA gold dataset files.")
    parser.add_argument("--gold-tuples", default="data/pubevent_soa_lite/gold_tuples.jsonl")
    parser.add_argument("--gold-event-chains", default="data/pubevent_soa_lite/gold_event_chains.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence.jsonl")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
