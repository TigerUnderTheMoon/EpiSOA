"""Audit script for evidence source_type distribution and balance."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl


DEFAULT_INPUT = Path("data/pubevent_soa_lite/evidence_filtered.jsonl")
DEFAULT_OUTPUT = Path("data/pubevent_soa_lite/interim/source_type_audit.json")

VALID_SOURCE_TYPES = {"official", "mainstream_news", "social_media", "forum", "public_interaction", "public_web"}
BALANCE_THRESHOLD_MIN = 0.05
BALANCE_THRESHOLD_MAX = 0.60


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return audit_source_type(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit evidence source_type distribution and balance.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-share", type=float, default=BALANCE_THRESHOLD_MIN, help="Minimum acceptable share for any source type")
    parser.add_argument("--max-share", type=float, default=BALANCE_THRESHOLD_MAX, help="Maximum acceptable share for any source type")
    return parser


def audit_source_type(args: argparse.Namespace) -> int:
    evidence = read_jsonl(args.input)
    if not evidence:
        print(f"No evidence found in {args.input}")
        return 1

    source_type_counter = Counter()
    events_with_source_type_none: list[str] = []
    per_event_distribution: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    source_balance_risk_events: list[dict[str, Any]] = []

    for item in evidence:
        event_id = str(item.get("event_id", ""))
        source_type = item.get("source_type")

        if not source_type or source_type == "":
            source_type_counter["none"] += 1
            if event_id not in events_with_source_type_none:
                events_with_source_type_none.append(event_id)
        else:
            source_type_counter[source_type] += 1

        per_event_distribution[event_id][source_type or "none"] += 1

    total = len(evidence)
    for event_id, dist in per_event_distribution.items():
        event_total = sum(dist.values())
        if event_total == 0:
            continue

        risk_sources = []
        for st, count in dist.items():
            share = count / event_total
            if share < args.min_share and count > 0:
                risk_sources.append({"source_type": st, "count": count, "share": round(share, 4), "risk": "too_low"})
            if share > args.max_share:
                risk_sources.append({"source_type": st, "count": count, "share": round(share, 4), "risk": "too_high"})

        if risk_sources:
            source_balance_risk_events.append({
                "event_id": event_id,
                "total_evidence": event_total,
                "distribution": dict(dist),
                "risks": risk_sources,
            })

    audit_report = {
        "total_evidence": total,
        "source_type_counter": dict(source_type_counter),
        "source_type_share": {st: round(count / total, 4) for st, count in source_type_counter.items()},
        "events_with_source_type_none": events_with_source_type_none,
        "events_with_source_type_none_count": len(events_with_source_type_none),
        "per_event_distribution": {k: dict(v) for k, v in sorted(per_event_distribution.items())},
        "source_balance_risk_events": source_balance_risk_events,
        "source_balance_risk_count": len(source_balance_risk_events),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Source type audit report written to {args.output}")
    print(f"\n=== Source Type Distribution ===")
    for st, count in sorted(source_type_counter.items(), key=lambda x: x[1], reverse=True):
        print(f"  {st}: {count} ({count/total:.1%})")

    print(f"\n=== Events with source_type=None ===")
    print(f"  Count: {len(events_with_source_type_none)}")
    if events_with_source_type_none:
        print(f"  Event IDs: {', '.join(events_with_source_type_none[:10])}{'...' if len(events_with_source_type_none) > 10 else ''}")

    print(f"\n=== Source Balance Risk Events ===")
    print(f"  Count: {len(source_balance_risk_events)}")
    if source_balance_risk_events:
        for risk_event in source_balance_risk_events[:5]:
            print(f"  {risk_event['event_id']}: {risk_event['risks']}")
        if len(source_balance_risk_events) > 5:
            print(f"  ... and {len(source_balance_risk_events) - 5} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
