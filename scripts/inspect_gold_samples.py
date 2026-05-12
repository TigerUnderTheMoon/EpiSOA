"""Print gold tuple samples for manual inspection."""

from __future__ import annotations

import argparse

from episoa.annotation.gold_annotation import inspect_gold_samples


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = inspect_gold_samples(
        gold_tuples_path=args.gold_tuples,
        gold_event_chains_path=args.gold_event_chains,
        events_path=args.events,
        evidence_path=args.evidence,
        event_id=args.event_id,
        num_events=args.num_events,
        seed=args.seed,
        output_path=args.output,
        show_evidence=True,
    )
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect gold tuple and event-chain samples.")
    parser.add_argument("--gold-tuples", default="data/pubevent_soa_lite/gold_tuples.jsonl")
    parser.add_argument("--gold-event-chains", default="data/pubevent_soa_lite/gold_event_chains.jsonl")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence.jsonl")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--num-events", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="data/pubevent_soa_lite/annotation/gold_inspection_samples.md")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
