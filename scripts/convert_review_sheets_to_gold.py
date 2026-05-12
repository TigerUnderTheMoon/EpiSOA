"""Convert human-reviewed sheets into gold JSONL files."""

from __future__ import annotations

import argparse
import json

from episoa.annotation.gold_annotation import convert_review_sheets_to_gold


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write_to_dataset_gold:
        print("WARNING: This will write human-reviewed gold files into data/pubevent_soa_lite/.")
        print("Only proceed if the review sheet has been manually checked.")
    summary = convert_review_sheets_to_gold(
        review_sheet=args.tuple_review_sheet,
        chain_review_sheet=args.chain_review_sheet,
        new_tuples=args.new_tuples,
        evidence_path=args.evidence,
        events_path=args.events,
        output_dir=args.output_dir,
        write_to_dataset_gold=args.write_to_dataset_gold,
        dataset_dir=args.dataset_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert reviewed gold annotation sheets to JSONL.")
    parser.add_argument("--tuple-review-sheet", "--review-sheet", dest="tuple_review_sheet", default="data/pubevent_soa_lite/annotation/gold_tuple_review_sheet.csv")
    parser.add_argument("--chain-review-sheet", default="data/pubevent_soa_lite/annotation/gold_chain_review_sheet.csv")
    parser.add_argument("--new-tuples", default="")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence.jsonl")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--output-dir", default="data/pubevent_soa_lite")
    parser.add_argument("--dataset-dir", default="data/pubevent_soa_lite")
    parser.add_argument("--write-to-dataset-gold", action="store_true")
    parser.add_argument("--use-llm-chain-summary", action="store_true", help="Reserved; default summaries are rule-generated.")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
