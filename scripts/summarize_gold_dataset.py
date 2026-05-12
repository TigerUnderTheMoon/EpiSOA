#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Summarize PubEvent-SOA Lite gold dataset.

Outputs:
- JSON statistics
- Markdown statistics report

This script is read-only: it does not modify source files.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


def read_jsonl(path):
    path = Path(path)
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at {path}:{lineno}: {e}") from e
    return rows


def get_event_id(obj):
    return obj.get("event_id") or obj.get("event") or obj.get("id") or "<missing_event_id>"


def normalize_missing(value, missing_label="<missing>"):
    if value is None:
        return missing_label
    if isinstance(value, str) and not value.strip():
        return missing_label
    return str(value)


def safe_stats(values):
    values = list(values)
    if not values:
        return {
            "min": 0,
            "max": 0,
            "mean": 0.0,
        }
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 4),
    }


def infer_chain_length(chain_obj):
    """
    Try to infer chain length from common list-like fields.
    If no list-like field exists, treat the row as one chain item.
    """
    candidate_keys = [
        "evidence_ids",
        "tuple_ids",
        "candidate_ids",
        "items",
        "steps",
        "nodes",
        "links",
        "chain",
        "event_chain",
    ]

    for key in candidate_keys:
        value = chain_obj.get(key)
        if isinstance(value, list):
            return len(value)

    # Some schemas store one evidence / tuple per chain row.
    for key in ["evidence_id", "tuple_id", "candidate_id"]:
        if chain_obj.get(key):
            return 1

    return 1


def pct(part, total):
    if total == 0:
        return 0.0
    return round(part * 100.0 / total, 2)


def sorted_counter(counter):
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--tuples", required=True)
    parser.add_argument("--chains", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    events = read_jsonl(args.events)
    evidence = read_jsonl(args.evidence)
    tuples = read_jsonl(args.tuples)
    chains = read_jsonl(args.chains)

    event_ids = [get_event_id(x) for x in events]
    event_id_set = set(event_ids)

    evidence_by_event = Counter(get_event_id(x) for x in evidence)
    tuples_by_event = Counter(get_event_id(x) for x in tuples)
    chains_by_event = Counter(get_event_id(x) for x in chains)

    source_type_dist = Counter(normalize_missing(x.get("source_type")) for x in evidence)
    sentiment_dist = Counter(normalize_missing(x.get("sentiment")) for x in tuples)
    support_label_dist = Counter(normalize_missing(x.get("support_label")) for x in tuples)

    chain_lengths = [infer_chain_length(x) for x in chains]
    chain_length_dist = Counter(str(x) for x in chain_lengths)

    per_event = []
    for eid in sorted(event_id_set):
        per_event.append({
            "event_id": eid,
            "evidence_count": evidence_by_event.get(eid, 0),
            "tuple_count": tuples_by_event.get(eid, 0),
            "chain_count": chains_by_event.get(eid, 0),
        })

    evidence_counts = [row["evidence_count"] for row in per_event]
    tuple_counts = [row["tuple_count"] for row in per_event]
    chain_counts = [row["chain_count"] for row in per_event]

    total_events = len(event_id_set)
    total_evidence = len(evidence)
    total_tuples = len(tuples)
    total_chains = len(chains)

    summary = {
        "dataset": {
            "event_count": total_events,
            "evidence_count": total_evidence,
            "tuple_count": total_tuples,
            "chain_count": total_chains,
        },
        "averages": {
            "evidence_per_event": round(total_evidence / total_events, 4) if total_events else 0.0,
            "tuples_per_event": round(total_tuples / total_events, 4) if total_events else 0.0,
            "chains_per_event": round(total_chains / total_events, 4) if total_events else 0.0,
        },
        "per_event_count_stats": {
            "evidence": safe_stats(evidence_counts),
            "tuples": safe_stats(tuple_counts),
            "chains": safe_stats(chain_counts),
        },
        "distributions": {
            "source_type": sorted_counter(source_type_dist),
            "sentiment": sorted_counter(sentiment_dist),
            "support_label": sorted_counter(support_label_dist),
            "chain_length": sorted_counter(chain_length_dist),
        },
        "per_event_counts": per_event,
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    with output_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    md_lines = []
    md_lines.append("# PubEvent-SOA Lite Gold Dataset Statistics")
    md_lines.append("")
    md_lines.append("## Overview")
    md_lines.append("")
    md_lines.append("| Metric | Value |")
    md_lines.append("|---|---:|")
    md_lines.append(f"| Events | {total_events} |")
    md_lines.append(f"| Evidence records | {total_evidence} |")
    md_lines.append(f"| Gold tuples | {total_tuples} |")
    md_lines.append(f"| Gold event chains | {total_chains} |")
    md_lines.append(f"| Avg. evidence per event | {summary['averages']['evidence_per_event']} |")
    md_lines.append(f"| Avg. tuples per event | {summary['averages']['tuples_per_event']} |")
    md_lines.append(f"| Avg. chains per event | {summary['averages']['chains_per_event']} |")
    md_lines.append("")

    md_lines.append("## Source Type Distribution")
    md_lines.append("")
    md_lines.append("| Source type | Count | Percent |")
    md_lines.append("|---|---:|---:|")
    for key, val in sorted_counter(source_type_dist).items():
        md_lines.append(f"| {key} | {val} | {pct(val, total_evidence)}% |")
    md_lines.append("")

    md_lines.append("## Sentiment Distribution")
    md_lines.append("")
    md_lines.append("| Sentiment | Count | Percent |")
    md_lines.append("|---|---:|---:|")
    for key, val in sorted_counter(sentiment_dist).items():
        md_lines.append(f"| {key} | {val} | {pct(val, total_tuples)}% |")
    md_lines.append("")

    md_lines.append("## Support Label Distribution")
    md_lines.append("")
    md_lines.append("| Support label | Count | Percent |")
    md_lines.append("|---|---:|---:|")
    for key, val in sorted_counter(support_label_dist).items():
        md_lines.append(f"| {key} | {val} | {pct(val, total_tuples)}% |")
    md_lines.append("")

    md_lines.append("## Chain Length Distribution")
    md_lines.append("")
    md_lines.append("| Chain length | Count | Percent |")
    md_lines.append("|---|---:|---:|")
    for key, val in sorted_counter(chain_length_dist).items():
        md_lines.append(f"| {key} | {val} | {pct(val, total_chains)}% |")
    md_lines.append("")

    md_lines.append("## Per-Event Counts")
    md_lines.append("")
    md_lines.append("| Event ID | Evidence | Tuples | Chains |")
    md_lines.append("|---|---:|---:|---:|")
    for row in per_event:
        md_lines.append(
            f"| {row['event_id']} | {row['evidence_count']} | {row['tuple_count']} | {row['chain_count']} |"
        )
    md_lines.append("")

    with output_md.open("w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print("=== Gold Dataset Statistics ===")
    print(f"Events:       {total_events}")
    print(f"Evidence:     {total_evidence}")
    print(f"Gold tuples:  {total_tuples}")
    print(f"Gold chains:  {total_chains}")
    print(f"Output JSON:  {output_json}")
    print(f"Output MD:    {output_md}")


if __name__ == "__main__":
    main()
