"""Audit gold annotation files for correctness, completeness, and consistency.

Checks:
  - event coverage (do all events in scope have tuples/chains?)
  - tuple_count_min (each event >= 3 tuples)
  - chain_count_min (each event >= 2 chains)
  - duplicate_candidate_ids
  - duplicate_chain_ids
  - missing_chain_ids
  - invalid_sentiments (must be in canonical set)
  - invalid_support_labels (must be in canonical set)
  - missing_evidence_refs (evidence_ids must exist in canonical evidence)
  - missing_source_type (tuples and chains must have source_type)

IMPORTANT: Uses evidence_v3_repaired_plus_low37.jsonl as canonical evidence.
Do NOT use evidence_filtered.jsonl to audit gold annotation.
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
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_ANNOTATION_DIR = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37"
)
DEFAULT_TUPLES = DEFAULT_ANNOTATION_DIR / "llm_gold_tuples.jsonl"
DEFAULT_CHAINS = DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains.jsonl"

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
VALID_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "unclear"}

TUPLES_MIN = 3
CHAINS_MIN = 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return audit(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit gold annotation files for correctness and consistency. "
                    "Uses evidence_v3_repaired_plus_low37.jsonl as canonical evidence namespace."
    )
    parser.add_argument("--events", default=str(DEFAULT_EVENTS),
                        help="Path to events.jsonl")
    parser.add_argument("--evidence", default=str(CANONICAL_EVIDENCE),
                        help="Path to canonical evidence JSONL "
                             "(default: evidence_v3_repaired_plus_low37.jsonl)")
    parser.add_argument("--tuples", default=str(DEFAULT_TUPLES),
                        help="Path to llm_gold_tuples.jsonl")
    parser.add_argument("--chains", default=str(DEFAULT_CHAINS),
                        help="Path to llm_gold_event_chains.jsonl")
    parser.add_argument("--max-events", type=int, default=None,
                        help="Limit audit to first N events (None = all)")
    parser.add_argument("--output", default=None,
                        help="Path to write audit report JSON (default: stdout)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress detailed output, return exit code only")
    return parser


def audit(args: argparse.Namespace) -> int:
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

    evidence_ids = {ev["evidence_id"] for ev in evidence}
    issues: list[dict[str, Any]] = []
    check_results: dict[str, str] = {}

    if not events:
        report = _build_report([], [], [], issues, check_results, args.evidence,
                               str(tuples_path), str(chains_path), {"error": "no_events_file"})
        _print_report(report, args)
        return 1

    # ---- event coverage ----
    tuple_event_ids = {t["event_id"] for t in tuples}
    chain_event_ids = {c["event_id"] for c in chains}

    missing_tuple_events = sorted(event_ids_in_scope - tuple_event_ids)
    missing_chain_events = sorted(event_ids_in_scope - chain_event_ids)

    if missing_tuple_events:
        issues.append({
            "type": "missing_tuple_event_coverage",
            "detail": f"Events with no tuples: {missing_tuple_events}",
            "count": len(missing_tuple_events),
        })
    if missing_chain_events:
        issues.append({
            "type": "missing_chain_event_coverage",
            "detail": f"Events with no chains: {missing_chain_events}",
            "count": len(missing_chain_events),
        })

    check_results["event_coverage"] = (
        "PASS" if not missing_tuple_events and not missing_chain_events else "FAIL"
    )

    # ---- tuple / chain count minimums ----
    tuple_counts = Counter(t["event_id"] for t in tuples)
    chain_counts = Counter(c["event_id"] for c in chains)

    low_tuple_events = {
        eid: cnt for eid, cnt in sorted(tuple_counts.items()) if cnt < TUPLES_MIN
    }
    low_chain_events = {
        eid: cnt for eid, cnt in sorted(chain_counts.items()) if cnt < CHAINS_MIN
    }

    for eid in sorted(event_ids_in_scope):
        tc = tuple_counts.get(eid, 0)
        if tc < TUPLES_MIN:
            issues.append({
                "type": "tuple_count_below_min",
                "event_id": eid,
                "count": tc,
                "minimum": TUPLES_MIN,
            })
        cc = chain_counts.get(eid, 0)
        if cc < CHAINS_MIN:
            issues.append({
                "type": "chain_count_below_min",
                "event_id": eid,
                "count": cc,
                "minimum": CHAINS_MIN,
            })

    check_results["tuple_count_min_ge_3"] = "PASS" if not low_tuple_events else "FAIL"
    check_results["chain_count_min_ge_2"] = "PASS" if not low_chain_events else "FAIL"

    # ---- duplicate candidate_ids ----
    candidate_ids = [t["candidate_id"] for t in tuples]
    dup_cids = {k: v for k, v in Counter(candidate_ids).items() if v > 1}
    if dup_cids:
        issues.append({
            "type": "duplicate_candidate_ids",
            "detail": f"{len(dup_cids)} duplicate candidate_ids",
            "duplicates": dup_cids,
        })
    check_results["candidate_id_duplicates"] = "PASS" if not dup_cids else "FAIL"

    # ---- duplicate chain_ids (using candidate_chain_id which is the unique key) ----
    chain_cids = [c.get("candidate_chain_id", "") for c in chains]
    dup_ccids = {k: v for k, v in Counter(chain_cids).items() if v > 1}
    if dup_ccids:
        issues.append({
            "type": "duplicate_candidate_chain_ids",
            "detail": f"{len(dup_ccids)} duplicate candidate_chain_ids",
            "duplicates": dup_ccids,
        })
    check_results["chain_id_duplicates"] = "PASS" if not dup_ccids else "FAIL"

    # ---- missing chain_ids (short-form CHAIN_EXXX_NNN) ----
    missing_cids = [
        c.get("candidate_chain_id", "?")
        for c in chains
        if not c.get("chain_id")
    ]
    if missing_cids:
        issues.append({
            "type": "missing_chain_ids",
            "detail": f"{len(missing_cids)} chain records missing chain_id field",
            "records": missing_cids[:20],
        })
    check_results["missing_chain_ids"] = "PASS" if not missing_cids else "FAIL"

    # also check for duplicate short-form chain_ids
    short_chain_ids = [c.get("chain_id", "") for c in chains if c.get("chain_id")]
    dup_scids = {k: v for k, v in Counter(short_chain_ids).items() if v > 1}
    if dup_scids:
        issues.append({
            "type": "duplicate_short_chain_ids",
            "detail": f"{len(dup_scids)} duplicate chain_id (short-form) values",
            "duplicates": dup_scids,
        })
        if check_results["chain_id_duplicates"] == "PASS":
            check_results["chain_id_duplicates"] = "FAIL"

    # ---- invalid sentiments ----
    for t in tuples:
        sentiment = t.get("sentiment", "")
        if sentiment not in VALID_SENTIMENTS:
            issues.append({
                "type": "invalid_sentiment",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
                "value": sentiment,
            })
    check_results["invalid_sentiments"] = (
        "PASS"
        if not any(i["type"] == "invalid_sentiment" for i in issues)
        else "FAIL"
    )

    # ---- invalid support_labels ----
    for t in tuples:
        sl = t.get("support_label", "")
        if sl not in VALID_SUPPORT_LABELS:
            issues.append({
                "type": "invalid_support_label",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
                "value": sl,
            })
    check_results["invalid_support_labels"] = (
        "PASS"
        if not any(i["type"] == "invalid_support_label" for i in issues)
        else "FAIL"
    )

    # ---- missing evidence refs ----
    for t in tuples:
        for eid in t.get("evidence_ids", []):
            if eid not in evidence_ids:
                issues.append({
                    "type": "missing_evidence_ref",
                    "record_type": "tuple",
                    "candidate_id": t["candidate_id"],
                    "event_id": t["event_id"],
                    "evidence_id": eid,
                })
    for c in chains:
        for eid in c.get("evidence_ids", []):
            if eid not in evidence_ids:
                issues.append({
                    "type": "missing_evidence_ref",
                    "record_type": "chain",
                    "candidate_chain_id": c.get("candidate_chain_id", "?"),
                    "event_id": c["event_id"],
                    "evidence_id": eid,
                })

    check_results["missing_evidence_refs"] = (
        "PASS"
        if not any(i["type"] == "missing_evidence_ref" for i in issues)
        else "FAIL"
    )

    # ---- missing source_type ----
    for t in tuples:
        if not t.get("source_type"):
            issues.append({
                "type": "missing_source_type",
                "record_type": "tuple",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
            })
    for c in chains:
        if not c.get("source_type"):
            issues.append({
                "type": "missing_source_type",
                "record_type": "chain",
                "candidate_chain_id": c.get("candidate_chain_id", "?"),
                "event_id": c["event_id"],
            })

    check_results["missing_source_type"] = (
        "PASS"
        if not any(i["type"] == "missing_source_type" for i in issues)
        else "FAIL"
    )

    # ---- summary ----
    eid_set = event_ids_in_scope if event_ids_in_scope else (
        set(tuple_counts.keys()) | set(chain_counts.keys())
    )
    event_counts = {
        eid: {
            "tuple_count": tuple_counts.get(eid, 0),
            "chain_count": chain_counts.get(eid, 0),
        }
        for eid in sorted(eid_set)
    }

    report = _build_report(
        tuples, chains, events, issues, check_results,
        args.evidence, str(tuples_path), str(chains_path), event_counts,
    )

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

    return 0 if report["ready_for_final_gold"] else 1


def _build_report(
    tuples: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    events: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    check_results: dict[str, str],
    evidence_path: str,
    tuples_path: str,
    chains_path: str,
    event_counts: dict[str, Any],
) -> dict[str, Any]:
    ready = all(v == "PASS" for v in check_results.values())
    return {
        "audit_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canonical_evidence_file": evidence_path,
        "gold_tuple_file": tuples_path,
        "gold_chain_file": chains_path,
        "events_in_scope": len(events),
        "tuple_rows": len(tuples),
        "chain_rows": len(chains),
        "total_issues": len(issues),
        "checks": check_results,
        "issues": issues,
        "event_counts": event_counts,
        "ready_for_final_gold": ready,
        "note": (
            f"Audited against canonical evidence: {evidence_path}. "
            "Do NOT use evidence_filtered.jsonl for gold annotation audit."
        ),
    }


def _print_report(report: dict[str, Any], args: argparse.Namespace) -> None:
    print(f"=== Gold Annotation Audit ===")
    print(f"Timestamp:          {report['audit_timestamp']}")
    print(f"Evidence file:      {report['canonical_evidence_file']}")
    print(f"Events in scope:    {report['events_in_scope']}")
    print(f"Tuple rows:         {report['tuple_rows']}")
    print(f"Chain rows:         {report['chain_rows']}")
    print(f"Total issues:       {report['total_issues']}")
    print(f"Ready for final:    {report['ready_for_final_gold']}")
    print()

    if not args.quiet:
        print("--- Checks ---")
        for check, result in sorted(report["checks"].items()):
            mark = "PASS" if result == "PASS" else "FAIL"
            print(f"  [{mark}] {check}")

        if report["issues"]:
            print(f"\n--- Issues ({len(report['issues'])}) ---")
            for issue in report["issues"]:
                detail = issue.get("detail", json.dumps(issue, ensure_ascii=False))
                print(f"  [{issue['type']}] {detail}")

        if report.get("event_counts"):
            print("\n--- Per-Event Counts ---")
            for eid, counts in sorted(report["event_counts"].items()):
                tc = counts["tuple_count"]
                cc = counts["chain_count"]
                tflag = "!" if tc < TUPLES_MIN else " "
                cflag = "!" if cc < CHAINS_MIN else " "
                print(f"  {eid}: {tc} tuples{tflag}  {cc} chains{cflag}")

        print(f"\nNOTE: {report['note']}")


if __name__ == "__main__":
    raise SystemExit(main())
