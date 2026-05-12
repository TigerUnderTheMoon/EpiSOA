"""Audit annotation expansion delta files before merge.

Checks delta files for:
  - candidate_id uniqueness (no overlap with existing, no internal duplicates)
  - chain_id presence (all chain records must have chain_id)
  - chain_id uniqueness (no overlap with existing, no internal duplicates)
  - evidence_id validity (must exist in canonical evidence)
  - sentiment / support_label validity
  - post-merge tuple/chain counts meet minimums

IMPORTANT: Uses evidence_v3_repaired_plus_low37.jsonl as canonical evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl

CANONICAL_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_ANNOTATION_DIR = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37"
)
DEFAULT_TUPLES = DEFAULT_ANNOTATION_DIR / "llm_gold_tuples.jsonl"
DEFAULT_CHAINS = DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains.jsonl"
DEFAULT_DELTA_TUPLES = DEFAULT_ANNOTATION_DIR / "llm_gold_tuples_expansion_delta.jsonl"
DEFAULT_DELTA_CHAINS = DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains_expansion_delta.jsonl"
DEFAULT_EXPANSION_PLAN = DEFAULT_ANNOTATION_DIR / "annotation_expansion_plan.jsonl"

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
VALID_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "unclear"}

TUPLES_MIN = 3
CHAINS_MIN = 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return audit_delta(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit annotation expansion delta files before merging."
    )
    parser.add_argument("--tuples", default=str(DEFAULT_TUPLES),
                        help="Path to existing llm_gold_tuples.jsonl")
    parser.add_argument("--chains", default=str(DEFAULT_CHAINS),
                        help="Path to existing llm_gold_event_chains.jsonl")
    parser.add_argument("--delta-tuples", default=str(DEFAULT_DELTA_TUPLES),
                        help="Path to delta tuples JSONL")
    parser.add_argument("--delta-chains", default=str(DEFAULT_DELTA_CHAINS),
                        help="Path to delta chains JSONL")
    parser.add_argument("--evidence", default=str(CANONICAL_EVIDENCE),
                        help="Path to canonical evidence JSONL")
    parser.add_argument("--expansion-plan", default=str(DEFAULT_EXPANSION_PLAN),
                        help="Path to expansion plan JSONL (optional)")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl",
                        help="Path to events.jsonl (for scoping)")
    parser.add_argument("--max-events", type=int, default=None,
                        help="Limit audit to first N events")
    parser.add_argument("--output", default=None,
                        help="Path to write audit report JSON (default: stdout)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress detailed output")
    return parser


def audit_delta(args: argparse.Namespace) -> int:
    tuples_path = Path(args.tuples)
    chains_path = Path(args.chains)
    delta_tuples_path = Path(args.delta_tuples)
    delta_chains_path = Path(args.delta_chains)
    evidence_path = Path(args.evidence)
    plan_path = Path(args.expansion_plan) if args.expansion_plan else None

    existing_tuples = read_jsonl(str(tuples_path)) if tuples_path.exists() else []
    existing_chains = read_jsonl(str(chains_path)) if chains_path.exists() else []
    delta_tuples = read_jsonl(str(delta_tuples_path)) if delta_tuples_path.exists() else []
    delta_chains = read_jsonl(str(delta_chains_path)) if delta_chains_path.exists() else []
    evidence = read_jsonl(str(evidence_path)) if evidence_path.exists() else []

    if not delta_tuples and not delta_chains:
        print("No delta files found or delta files are empty.")
        return 1

    events_path = Path(args.events)
    if args.max_events:
        all_events = read_jsonl(str(events_path)) if events_path.exists() else []
        scoped_events = all_events[:args.max_events]
        ev_set = {e["event_id"] for e in scoped_events}
        delta_tuples = [t for t in delta_tuples if t["event_id"] in ev_set]
        delta_chains = [c for c in delta_chains if c["event_id"] in ev_set]
        existing_tuples = [t for t in existing_tuples if t["event_id"] in ev_set]
        existing_chains = [c for c in existing_chains if c["event_id"] in ev_set]

    evidence_ids = {ev["evidence_id"] for ev in evidence}
    issues: list[dict[str, Any]] = []
    checks: dict[str, str] = {}

    # ---- candidate_id overlap with existing ----
    existing_cids = {t["candidate_id"] for t in existing_tuples}
    delta_cids = [t["candidate_id"] for t in delta_tuples]
    overlap = existing_cids & set(delta_cids)
    if overlap:
        issues.append({
            "type": "duplicate_candidate_id_with_existing",
            "detail": f"{len(overlap)} candidate_ids overlap with existing: {sorted(overlap)}",
        })
    checks["candidate_id_overlap"] = "PASS" if not overlap else "FAIL"

    # ---- candidate_id internal duplicates ----
    dup_delta_cids = {k: v for k, v in Counter(delta_cids).items() if v > 1}
    if dup_delta_cids:
        issues.append({
            "type": "duplicate_candidate_id_within_delta",
            "detail": f"{len(dup_delta_cids)} candidate_ids duplicated within delta",
            "duplicates": dup_delta_cids,
        })
    checks["candidate_id_internal_duplicates"] = "PASS" if not dup_delta_cids else "FAIL"

    # ---- chain_id overlap with existing ----
    existing_chain_cids = {c.get("candidate_chain_id", "") for c in existing_chains}
    delta_chain_cids = [c.get("candidate_chain_id", "") for c in delta_chains]
    chain_overlap = existing_chain_cids & set(delta_chain_cids)
    if chain_overlap:
        issues.append({
            "type": "duplicate_chain_id_with_existing",
            "detail": f"{len(chain_overlap)} chain_ids overlap with existing: {sorted(chain_overlap)}",
        })
    checks["chain_id_overlap"] = "PASS" if not chain_overlap else "FAIL"

    # ---- chain_id internal duplicates ----
    dup_delta_ccids = {k: v for k, v in Counter(delta_chain_cids).items() if v > 1}
    if dup_delta_ccids:
        issues.append({
            "type": "duplicate_chain_id_within_delta",
            "detail": f"{len(dup_delta_ccids)} chain_ids duplicated within delta",
            "duplicates": dup_delta_ccids,
        })
    checks["chain_id_internal_duplicates"] = "PASS" if not dup_delta_ccids else "FAIL"

    # ---- missing chain_id (short-form) in delta chains ----
    missing_chain_ids = [
        c.get("candidate_chain_id", "?")
        for c in delta_chains
        if not c.get("chain_id")
    ]
    if missing_chain_ids:
        issues.append({
            "type": "missing_chain_id_in_delta",
            "detail": f"{len(missing_chain_ids)} delta chain records missing chain_id field",
            "records": missing_chain_ids[:20],
        })
    checks["delta_missing_chain_ids"] = "PASS" if not missing_chain_ids else "FAIL"

    # ---- short-form chain_id overlap ----
    existing_short_chain_ids = {c.get("chain_id", "") for c in existing_chains if c.get("chain_id")}
    delta_short_chain_ids = [c.get("chain_id", "") for c in delta_chains if c.get("chain_id")]
    short_overlap = existing_short_chain_ids & set(delta_short_chain_ids)
    if short_overlap:
        issues.append({
            "type": "duplicate_short_chain_id_with_existing",
            "detail": f"{len(short_overlap)} short-form chain_ids overlap: {sorted(short_overlap)}",
        })
    dup_delta_scids = {k: v for k, v in Counter(delta_short_chain_ids).items() if v > 1}
    if dup_delta_scids:
        issues.append({
            "type": "duplicate_short_chain_id_within_delta",
            "detail": f"{len(dup_delta_scids)} short-form chain_ids duplicated in delta",
            "duplicates": dup_delta_scids,
        })
    checks["delta_chain_id_duplicates"] = (
        "PASS" if not short_overlap and not dup_delta_scids else "FAIL"
    )

    # ---- evidence_id validity ----
    for t in delta_tuples:
        for eid in t.get("evidence_ids", []):
            if eid not in evidence_ids:
                issues.append({
                    "type": "invalid_evidence_id",
                    "record_type": "tuple",
                    "candidate_id": t["candidate_id"],
                    "event_id": t["event_id"],
                    "evidence_id": eid,
                })
        if not t.get("evidence_ids"):
            issues.append({
                "type": "empty_evidence_ids",
                "record_type": "tuple",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
            })

    for c in delta_chains:
        for eid in c.get("evidence_ids", []):
            if eid not in evidence_ids:
                issues.append({
                    "type": "invalid_evidence_id",
                    "record_type": "chain",
                    "candidate_chain_id": c.get("candidate_chain_id", "?"),
                    "event_id": c["event_id"],
                    "evidence_id": eid,
                })
        if not c.get("evidence_ids"):
            issues.append({
                "type": "empty_evidence_ids",
                "record_type": "chain",
                "candidate_chain_id": c.get("candidate_chain_id", "?"),
                "event_id": c["event_id"],
            })
    checks["evidence_id_validity"] = (
        "PASS"
        if not any(
            i["type"] in ("invalid_evidence_id", "empty_evidence_ids")
            for i in issues
        )
        else "FAIL"
    )

    # ---- sentiment / support_label validity ----
    for t in delta_tuples:
        if t.get("sentiment") not in VALID_SENTIMENTS:
            issues.append({
                "type": "invalid_sentiment",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
                "value": t.get("sentiment"),
            })
        if t.get("support_label") not in VALID_SUPPORT_LABELS:
            issues.append({
                "type": "invalid_support_label",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
                "value": t.get("support_label"),
            })
    checks["sentiment_support_validity"] = (
        "PASS"
        if not any(
            i["type"] in ("invalid_sentiment", "invalid_support_label")
            for i in issues
        )
        else "FAIL"
    )

    # ---- post-merge count check ----
    all_tuples = existing_tuples + delta_tuples
    all_chains = existing_chains + delta_chains
    t_counts = Counter(t["event_id"] for t in all_tuples)
    c_counts = Counter(c["event_id"] for c in all_chains)

    expansion_plan: list[dict[str, Any]] = []
    if plan_path and plan_path.exists():
        expansion_plan = read_jsonl(str(plan_path))

    all_event_ids = set(t_counts.keys()) | set(c_counts.keys())

    for eid in sorted(all_event_ids):
        tc = t_counts.get(eid, 0)
        cc = c_counts.get(eid, 0)
        if tc < TUPLES_MIN:
            issues.append({
                "type": "post_merge_tuple_count_low",
                "event_id": eid,
                "count": tc,
                "minimum": TUPLES_MIN,
            })
        if cc < CHAINS_MIN:
            issues.append({
                "type": "post_merge_chain_count_low",
                "event_id": eid,
                "count": cc,
                "minimum": CHAINS_MIN,
            })

    checks["post_merge_counts"] = (
        "PASS"
        if not any(
            i["type"] in ("post_merge_tuple_count_low", "post_merge_chain_count_low")
            for i in issues
        )
        else "FAIL"
    )

    # ---- expansion plan coverage ----
    if expansion_plan:
        plan_events = {p["event_id"] for p in expansion_plan}
        delta_events = {t["event_id"] for t in delta_tuples} | {
            c["event_id"] for c in delta_chains
        }
        uncovered = plan_events - delta_events
        if uncovered:
            issues.append({
                "type": "expansion_plan_not_covered",
                "detail": f"Plan events with no delta: {sorted(uncovered)}",
            })
        checks["plan_coverage"] = "PASS" if not uncovered else "FAIL"
    else:
        checks["plan_coverage"] = "N/A"

    # ---- build report ----
    ready = all(
        v == "PASS" for v in checks.values()
        if v != "N/A"
    )

    report = {
        "audit_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canonical_evidence_file": str(evidence_path),
        "existing_tuple_count": len(existing_tuples),
        "existing_chain_count": len(existing_chains),
        "delta_tuple_count": len(delta_tuples),
        "delta_chain_count": len(delta_chains),
        "merged_tuple_count": len(all_tuples),
        "merged_chain_count": len(all_chains),
        "total_issues": len(issues),
        "checks": checks,
        "issues": issues,
        "merge_safe": ready,
        "post_merge_event_counts": {
            eid: {"tuple_count": t_counts.get(eid, 0), "chain_count": c_counts.get(eid, 0)}
            for eid in sorted(all_event_ids)
        },
        "note": (
            f"Audited against canonical evidence: {evidence_path}. "
            "Do NOT use evidence_filtered.jsonl."
        ),
    }

    _print_report(report, args)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not args.quiet:
            print(f"\nReport written to {output_path}")

    return 0 if report["merge_safe"] else 1


def _print_report(report: dict[str, Any], args: argparse.Namespace) -> None:
    print(f"=== Expansion Delta Audit ===")
    print(f"Timestamp:              {report['audit_timestamp']}")
    print(f"Existing tuples/chains: {report['existing_tuple_count']}/{report['existing_chain_count']}")
    print(f"Delta tuples/chains:    {report['delta_tuple_count']}/{report['delta_chain_count']}")
    print(f"Merged would be:        {report['merged_tuple_count']}/{report['merged_chain_count']}")
    print(f"Total issues:           {report['total_issues']}")
    print(f"Merge safe:             {report['merge_safe']}")
    print()

    if not args.quiet:
        print("--- Checks ---")
        for check, result in sorted(report["checks"].items()):
            mark = "PASS" if result == "PASS" else ("N/A  " if result == "N/A" else "FAIL")
            print(f"  [{mark}] {check}")

        if report["issues"]:
            print(f"\n--- Issues ({len(report['issues'])}) ---")
            for issue in report["issues"]:
                detail = issue.get("detail", json.dumps(issue, ensure_ascii=False))
                print(f"  [{issue['type']}] {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
