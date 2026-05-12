"""Build annotation expansion plan for events with low tuple/chain counts.

Scans gold annotation and identifies events needing expansion:
  - tuple_count < 3
  - chain_count < 2

Assigns priority:
  - P0: both tuple and chain count below threshold, OR 0 tuples, OR 0 chains
  - P1: only one threshold unmet

Assigns task type:
  - expand_tuples_and_chains
  - expand_tuples_only
  - expand_chains_only

Outputs annotation_expansion_plan.jsonl.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl

CANONICAL_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_ANNOTATION_DIR = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37"
)
DEFAULT_TUPLES = DEFAULT_ANNOTATION_DIR / "llm_gold_tuples.jsonl"
DEFAULT_CHAINS = DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains.jsonl"

TUPLES_MIN = 3
CHAINS_MIN = 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return build_plan(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build annotation expansion plan for low-tuple/low-chain events."
    )
    parser.add_argument("--events", default=str(DEFAULT_EVENTS),
                        help="Path to events.jsonl")
    parser.add_argument("--evidence", default=str(CANONICAL_EVIDENCE),
                        help="Path to canonical evidence JSONL")
    parser.add_argument("--tuples", default=str(DEFAULT_TUPLES),
                        help="Path to llm_gold_tuples.jsonl")
    parser.add_argument("--chains", default=str(DEFAULT_CHAINS),
                        help="Path to llm_gold_event_chains.jsonl")
    parser.add_argument("--max-events", type=int, default=None,
                        help="Limit to first N events (None = all)")
    parser.add_argument("--output", default=None,
                        help="Output path for expansion plan JSONL "
                             "(default: annotation_dir/annotation_expansion_plan.jsonl)")
    parser.add_argument("--tuple-min", type=int, default=TUPLES_MIN,
                        help="Minimum acceptable tuple count per event")
    parser.add_argument("--chain-min", type=int, default=CHAINS_MIN,
                        help="Minimum acceptable chain count per event")
    return parser


def build_plan(args: argparse.Namespace) -> int:
    events_path = Path(args.events)
    evidence_path = Path(args.evidence)
    tuples_path = Path(args.tuples)
    chains_path = Path(args.chains)

    events = read_jsonl(str(events_path)) if events_path.exists() else []
    evidence = read_jsonl(str(evidence_path)) if evidence_path.exists() else []
    tuples = read_jsonl(str(tuples_path)) if tuples_path.exists() else []
    chains = read_jsonl(str(chains_path)) if chains_path.exists() else []

    if args.max_events:
        events = events[: args.max_events]
        event_ids_in_scope = {e["event_id"] for e in events}
        tuples = [t for t in tuples if t["event_id"] in event_ids_in_scope]
        chains = [c for c in chains if c["event_id"] in event_ids_in_scope]
    else:
        event_ids_in_scope = {e["event_id"] for e in events}

    tuple_counts = Counter(t["event_id"] for t in tuples)
    chain_counts = Counter(c["event_id"] for c in chains)

    from collections import defaultdict
    evidence_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in evidence:
        evidence_by_event[ev["event_id"]].append(ev)

    plan: list[dict[str, Any]] = []

    for eid in sorted(event_ids_in_scope):
        tc = tuple_counts.get(eid, 0)
        cc = chain_counts.get(eid, 0)

        low_t = tc < args.tuple_min
        low_c = cc < args.chain_min

        if not low_t and not low_c:
            continue

        if tc == 0 or cc == 0 or (low_t and low_c):
            priority = "P0"
        else:
            priority = "P1"

        if low_t and low_c:
            task = "expand_tuples_and_chains"
        elif low_t:
            task = "expand_tuples_only"
        else:
            task = "expand_chains_only"

        ev_evidence = evidence_by_event.get(eid, [])
        source_dist = Counter(
            ev.get("source_type", ev.get("source", "unknown"))
            for ev in ev_evidence
        )

        reasons = []
        if low_t:
            reasons.append("tuple_count below threshold")
        if low_c:
            reasons.append("chain_count below threshold")

        plan.append({
            "event_id": eid,
            "priority": priority,
            "task": task,
            "current_tuple_count": tc,
            "current_chain_count": cc,
            "target_min_tuple_count": args.tuple_min,
            "target_min_chain_count": args.chain_min,
            "evidence_count": len(ev_evidence),
            "source_dist": dict(source_dist),
            "reason": " and ".join(reasons),
        })

    output_path = Path(args.output) if args.output else (
        DEFAULT_ANNOTATION_DIR / "annotation_expansion_plan.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(str(output_path), plan)

    print(f"Found {len(plan)} events needing expansion:")
    for p in plan:
        print(f"  [{p['priority']}] {p['event_id']}: "
              f"tuples={p['current_tuple_count']}/{args.tuple_min} "
              f"chains={p['current_chain_count']}/{args.chain_min} "
              f"→ {p['task']}")

    if not plan:
        print("All events meet minimum thresholds. No expansion needed.")

    print(f"\nPlan written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
