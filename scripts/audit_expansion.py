"""Audit script for annotation expansion outputs.

Checks:
  - candidate_id uniqueness (no duplicates with existing or within delta)
  - evidence_id references exist in evidence file
  - sentiment and support_label are valid
  - tuple_count and chain_count per event after expansion meet targets
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl

BASE_DIR = Path("data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37")
EVIDENCE_PATH = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
VALID_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "unclear"}


def main() -> None:
    existing_tuples = read_jsonl(str(BASE_DIR / "llm_gold_tuples.jsonl"))
    existing_chains = read_jsonl(str(BASE_DIR / "llm_gold_event_chains.jsonl"))
    delta_tuples = read_jsonl(str(BASE_DIR / "llm_gold_tuples_expansion_delta.jsonl"))
    delta_chains = read_jsonl(str(BASE_DIR / "llm_gold_event_chains_expansion_delta.jsonl"))
    evidence = read_jsonl(str(EVIDENCE_PATH))
    expansion_plan = read_jsonl(str(BASE_DIR / "annotation_expansion_plan.jsonl"))
    debug_records = json.loads((BASE_DIR / "expansion_debug.json").read_text(encoding="utf-8"))

    evidence_ids = {ev["evidence_id"] for ev in evidence}

    all_tuples = existing_tuples + delta_tuples
    all_chains = existing_chains + delta_chains

    issues: list[dict[str, Any]] = []

    existing_candidate_ids = {t["candidate_id"] for t in existing_tuples}
    delta_candidate_ids = {t["candidate_id"] for t in delta_tuples}
    overlap = existing_candidate_ids & delta_candidate_ids
    if overlap:
        issues.append({
            "type": "duplicate_candidate_id",
            "detail": f"Delta tuples have {len(overlap)} candidate_ids that overlap with existing: {sorted(overlap)}",
        })

    delta_candidate_ids_list = [t["candidate_id"] for t in delta_tuples]
    if len(delta_candidate_ids_list) != len(set(delta_candidate_ids_list)):
        from collections import Counter
        dupes = {k: v for k, v in Counter(delta_candidate_ids_list).items() if v > 1}
        issues.append({
            "type": "duplicate_candidate_id_within_delta",
            "detail": f"Duplicate candidate_ids within delta: {dupes}",
        })

    existing_chain_ids = {c["candidate_chain_id"] for c in existing_chains}
    delta_chain_ids = {c["candidate_chain_id"] for c in delta_chains}
    chain_overlap = existing_chain_ids & delta_chain_ids
    if chain_overlap:
        issues.append({
            "type": "duplicate_chain_id",
            "detail": f"Delta chains have {len(chain_overlap)} chain_ids that overlap with existing: {sorted(chain_overlap)}",
        })

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
        for eid in t.get("evidence_ids", []):
            if eid not in evidence_ids:
                issues.append({
                    "type": "missing_evidence_id",
                    "candidate_id": t["candidate_id"],
                    "event_id": t["event_id"],
                    "evidence_id": eid,
                })
        if not t.get("evidence_ids"):
            issues.append({
                "type": "empty_evidence_ids",
                "candidate_id": t["candidate_id"],
                "event_id": t["event_id"],
            })

    for c in delta_chains:
        for eid in c.get("evidence_ids", []):
            if eid not in evidence_ids:
                issues.append({
                    "type": "missing_evidence_id_chain",
                    "candidate_chain_id": c["candidate_chain_id"],
                    "event_id": c["event_id"],
                    "evidence_id": eid,
                })
        if not c.get("evidence_ids"):
            issues.append({
                "type": "empty_evidence_ids_chain",
                "candidate_chain_id": c["candidate_chain_id"],
                "event_id": c["event_id"],
            })

    tuples_by_event: dict[str, int] = defaultdict(int)
    for t in all_tuples:
        tuples_by_event[t["event_id"]] += 1

    chains_by_event: dict[str, int] = defaultdict(int)
    for c in all_chains:
        chains_by_event[c["event_id"]] += 1

    for plan_item in expansion_plan:
        event_id = plan_item["event_id"]
        target_tuple = plan_item["target_min_tuple_count"]
        target_chain = plan_item["target_min_chain_count"]
        actual_tuple = tuples_by_event.get(event_id, 0)
        actual_chain = chains_by_event.get(event_id, 0)
        if actual_tuple < target_tuple:
            issues.append({
                "type": "tuple_count_below_target",
                "event_id": event_id,
                "target": target_tuple,
                "actual": actual_tuple,
            })
        if actual_chain < target_chain:
            issues.append({
                "type": "chain_count_below_target",
                "event_id": event_id,
                "target": target_chain,
                "actual": actual_chain,
            })

    report = {
        "audit_timestamp": "2026-05-13",
        "existing_tuple_count": len(existing_tuples),
        "existing_chain_count": len(existing_chains),
        "delta_tuple_count": len(delta_tuples),
        "delta_chain_count": len(delta_chains),
        "total_tuple_count": len(all_tuples),
        "total_chain_count": len(all_chains),
        "total_issues": len(issues),
        "issues": issues,
        "event_counts_after_expansion": {
            event_id: {
                "tuple_count": tuples_by_event.get(event_id, 0),
                "chain_count": chains_by_event.get(event_id, 0),
            }
            for event_id in sorted(set(list(tuples_by_event.keys()) + list(chains_by_event.keys())))
        },
    }

    audit_path = BASE_DIR / "expansion_audit.json"
    audit_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Audit complete: {len(issues)} issues found")
    if issues:
        for issue in issues:
            print(f"  [{issue['type']}] {issue.get('detail', issue)}")
    else:
        print("  All checks passed!")
    print(f"Audit report written to {audit_path}")


if __name__ == "__main__":
    main()
