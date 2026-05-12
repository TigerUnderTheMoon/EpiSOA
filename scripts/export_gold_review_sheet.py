#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict

TEXT_KEYS = ["text", "content", "snippet", "summary", "description", "body"]
TITLE_KEYS = ["title", "headline", "name"]
URL_KEYS = ["url", "source_url", "link"]


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def first_non_empty(obj, keys, default=""):
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return str(value)
    return default


def get_event_id(obj):
    return obj.get("event_id", "")


def get_evidence_id(obj):
    return obj.get("evidence_id") or obj.get("id") or obj.get("raw_id") or obj.get("candidate_id") or ""


def get_evidence_ids(obj):
    value = obj.get("evidence_ids")
    if isinstance(value, list):
        return [str(x) for x in value if x]
    value = obj.get("evidence_id")
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def chain_steps_text(chain):
    steps = chain.get("event_chain")
    if isinstance(steps, list):
        return " | ".join(str(x) for x in steps)
    if isinstance(steps, str):
        return steps
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--tuples", required=True)
    parser.add_argument("--chains", required=True)
    parser.add_argument("--event-ids", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    target_events = set(args.event_ids)

    evidence_rows = read_jsonl(args.evidence)
    tuple_rows = read_jsonl(args.tuples)
    chain_rows = read_jsonl(args.chains)

    evidence_by_id = {}
    for ev in evidence_rows:
        eid = get_evidence_id(ev)
        if eid:
            evidence_by_id[eid] = ev

    chains_by_event = defaultdict(list)
    for chain in chain_rows:
        eid = get_event_id(chain)
        if eid:
            chains_by_event[eid].append(chain)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "event_id",
        "candidate_id",
        "sentiment",
        "support_label",
        "stakeholder",
        "opinion",
        "rationale",
        "tuple_evidence_ids",
        "chain_ids",
        "chain_evidence_overlap",
        "chain_steps",
        "evidence_id",
        "source_type",
        "title",
        "url",
        "text",
        "review_decision",
        "review_note",
    ]

    target_tuple_count = 0
    tuple_with_chain_count = 0
    written = 0
    missing_evidence_refs = 0

    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for tup in tuple_rows:
            event_id = get_event_id(tup)
            if event_id not in target_events:
                continue

            target_tuple_count += 1
            tuple_eids = get_evidence_ids(tup)
            tuple_eid_set = set(tuple_eids)

            matched_chains = []
            for chain in chains_by_event.get(event_id, []):
                chain_id = chain.get("chain_id") or chain.get("candidate_chain_id") or ""
                chain_eids = set(get_evidence_ids(chain))
                overlap = sorted(tuple_eid_set & chain_eids)
                if overlap:
                    matched_chains.append({
                        "chain_id": chain_id,
                        "overlap": overlap,
                        "steps": chain_steps_text(chain),
                    })

            matched_chains.sort(key=lambda x: (-len(x["overlap"]), x["chain_id"]))

            if matched_chains:
                tuple_with_chain_count += 1

            chain_ids = [x["chain_id"] for x in matched_chains if x["chain_id"]]
            overlap_text = [
                f"{x['chain_id']}:{','.join(x['overlap'])}"
                for x in matched_chains
            ]
            chain_steps = [
                f"{x['chain_id']} => {x['steps']}"
                for x in matched_chains
                if x["steps"]
            ]

            if not tuple_eids:
                tuple_eids = [""]

            for evidence_id in tuple_eids:
                ev = evidence_by_id.get(evidence_id, {})
                if evidence_id and not ev:
                    missing_evidence_refs += 1

                writer.writerow({
                    "event_id": event_id,
                    "candidate_id": tup.get("candidate_id", ""),
                    "sentiment": tup.get("sentiment", ""),
                    "support_label": tup.get("support_label", ""),
                    "stakeholder": tup.get("stakeholder", ""),
                    "opinion": tup.get("opinion", ""),
                    "rationale": tup.get("rationale", ""),
                    "tuple_evidence_ids": ";".join(get_evidence_ids(tup)),
                    "chain_ids": ";".join(chain_ids),
                    "chain_evidence_overlap": " || ".join(overlap_text),
                    "chain_steps": " || ".join(chain_steps),
                    "evidence_id": evidence_id,
                    "source_type": ev.get("source_type", ""),
                    "title": first_non_empty(ev, TITLE_KEYS, ""),
                    "url": first_non_empty(ev, URL_KEYS, ""),
                    "text": first_non_empty(ev, TEXT_KEYS, ""),
                    "review_decision": "",
                    "review_note": "",
                })
                written += 1

    print("=== Gold Review Sheet Export ===")
    print(f"Target events:              {', '.join(sorted(target_events))}")
    print(f"Target tuples:              {target_tuple_count}")
    print(f"Tuples linked to chains:    {tuple_with_chain_count}")
    print(f"Rows written:               {written}")
    print(f"Missing evidence refs:      {missing_evidence_refs}")
    print(f"Output:                     {output}")


if __name__ == "__main__":
    main()
