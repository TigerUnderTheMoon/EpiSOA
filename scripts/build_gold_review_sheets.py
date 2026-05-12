"""Build human review sheets for gold annotation."""

from __future__ import annotations

import argparse
import json

from episoa.annotation.gold_annotation import build_gold_review_outputs, parse_event_ids


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_gold_review_outputs(
        events_path=args.events,
        evidence_path=args.evidence,
        verified_path=args.verified,
        chains_path=args.chains,
        annotation_sheet_path=args.annotation_sheet,
        output_dir=args.output_dir,
        event_ids=parse_event_ids(args.event_ids),
        max_events=args.max_events,
        include_supported_only=args.include_supported_only,
        include_weak=args.include_weak,
        include_issues=args.include_issues,
        sample_strategy=args.sample_strategy,
        use_llm_prelabel=args.use_llm_prelabel,
        dry_run=args.dry_run,
        llm_prelabeler=None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.use_llm_prelabel:
        print("LLM prelabel requested. No default LLM client is configured in this script; llm_prelabels.jsonl will contain suggestions only when a prelabeler is supplied programmatically.")
    if args.dry_run:
        print("dry-run enabled: review sheet files were not written.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build human review sheets for EpiSOA gold annotation.")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence.jsonl")
    parser.add_argument("--verified", default="outputs/runs/faithfulness_verification/verified_soa_tuples.jsonl")
    parser.add_argument("--chains", default="outputs/runs/event_chain_retrieval/event_chain_candidates.jsonl")
    parser.add_argument("--annotation-sheet", default="data/pubevent_soa_lite/annotation/annotation_sheet.csv")
    parser.add_argument("--output-dir", default="data/pubevent_soa_lite/annotation")
    parser.add_argument("--event-ids", default="")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--include-supported-only", action="store_true")
    parser.add_argument("--include-weak", action="store_true")
    parser.add_argument("--include-issues", action="store_true")
    parser.add_argument("--sample-strategy", default="input", choices=["input", "balanced"])
    parser.add_argument("--use-llm-prelabel", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
