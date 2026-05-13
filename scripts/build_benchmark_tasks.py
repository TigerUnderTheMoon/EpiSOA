#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Build benchmark task files from PubEvent-SOA Lite gold release.

Outputs:
1. tuple_identification.jsonl
   Event-level task: identify all SOA tuples from event evidence.

2. evidence_support_classification.jsonl
   Pair-level task: classify whether one evidence item supports a tuple.

3. chain_construction.jsonl
   Event-level task: construct event chains from event evidence.

The script is read-only with respect to source files.
"""

import argparse
import json
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


TEXT_KEYS = ["text", "content", "snippet", "summary", "description", "body"]
TITLE_KEYS = ["title", "headline", "name"]
URL_KEYS = ["url", "source_url", "link"]


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


def write_jsonl(path, rows, backup_existing=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and backup_existing:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_name(path.stem + f".backup_{timestamp}" + path.suffix)
        shutil.copy2(path, backup)

    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path, obj, backup_existing=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and backup_existing:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_name(path.stem + f".backup_{timestamp}" + path.suffix)
        shutil.copy2(path, backup)

    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


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
    return obj.get("event_id") or obj.get("event") or obj.get("id") or ""


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


def safe_id(value):
    value = str(value)
    out = []
    for ch in value:
        if ch.isalnum() or ch in ["_", "-", "."]:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def truncate_text(text, max_chars):
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def natural_event_sort_key(event_id):
    digits = "".join(ch for ch in str(event_id) if ch.isdigit())
    if digits:
        return (str(event_id).rstrip(digits), int(digits), str(event_id))
    return (str(event_id), 0, str(event_id))


def compact_event(event):
    event_id = get_event_id(event)
    compact = {"event_id": event_id}
    for key, value in event.items():
        if key not in compact:
            compact[key] = value
    return compact


def compact_evidence(evidence, max_text_chars):
    eid = get_evidence_id(evidence)
    return {
        "evidence_id": eid,
        "event_id": get_event_id(evidence),
        "source_type": evidence.get("source_type", ""),
        "title": first_non_empty(evidence, TITLE_KEYS, ""),
        "url": first_non_empty(evidence, URL_KEYS, ""),
        "text": truncate_text(first_non_empty(evidence, TEXT_KEYS, ""), max_text_chars),
    }


def compact_tuple(tuple_obj):
    return {
        "candidate_id": tuple_obj.get("candidate_id", ""),
        "event_id": get_event_id(tuple_obj),
        "stakeholder": tuple_obj.get("stakeholder", ""),
        "opinion": tuple_obj.get("opinion", ""),
        "sentiment": tuple_obj.get("sentiment", ""),
        "support_label": tuple_obj.get("support_label", ""),
        "evidence_ids": get_evidence_ids(tuple_obj),
        "rationale": tuple_obj.get("rationale", ""),
    }


def compact_tuple_claim(tuple_obj):
    return {
        "candidate_id": tuple_obj.get("candidate_id", ""),
        "event_id": get_event_id(tuple_obj),
        "stakeholder": tuple_obj.get("stakeholder", ""),
        "opinion": tuple_obj.get("opinion", ""),
        "sentiment": tuple_obj.get("sentiment", ""),
    }


def compact_chain(chain_obj):
    return {
        "chain_id": chain_obj.get("chain_id", ""),
        "candidate_chain_id": chain_obj.get("candidate_chain_id", ""),
        "event_id": get_event_id(chain_obj),
        "evidence_ids": get_evidence_ids(chain_obj),
        "event_chain": chain_obj.get("event_chain", []),
        "source_type": chain_obj.get("source_type", ""),
    }


def build_indices(events, evidence, tuples, chains):
    events_by_id = {}
    for event in events:
        event_id = get_event_id(event)
        if event_id:
            events_by_id[event_id] = event

    evidence_by_id = {}
    evidence_by_event = defaultdict(list)
    for ev in evidence:
        evidence_id = get_evidence_id(ev)
        event_id = get_event_id(ev)
        if evidence_id:
            evidence_by_id[evidence_id] = ev
        if event_id:
            evidence_by_event[event_id].append(ev)

    tuples_by_event = defaultdict(list)
    for tup in tuples:
        event_id = get_event_id(tup)
        if event_id:
            tuples_by_event[event_id].append(tup)

    chains_by_event = defaultdict(list)
    for chain in chains:
        event_id = get_event_id(chain)
        if event_id:
            chains_by_event[event_id].append(chain)

    return events_by_id, evidence_by_id, evidence_by_event, tuples_by_event, chains_by_event


def validate_refs(tuples, chains, evidence_by_id):
    missing_tuple_evidence = []
    missing_chain_evidence = []

    for tup in tuples:
        for evidence_id in get_evidence_ids(tup):
            if evidence_id not in evidence_by_id:
                missing_tuple_evidence.append({
                    "event_id": get_event_id(tup),
                    "candidate_id": tup.get("candidate_id", ""),
                    "evidence_id": evidence_id,
                })

    for chain in chains:
        for evidence_id in get_evidence_ids(chain):
            if evidence_id not in evidence_by_id:
                missing_chain_evidence.append({
                    "event_id": get_event_id(chain),
                    "chain_id": chain.get("chain_id", ""),
                    "evidence_id": evidence_id,
                })

    return {
        "missing_tuple_evidence_refs": missing_tuple_evidence,
        "missing_chain_evidence_refs": missing_chain_evidence,
    }


def build_tuple_identification(events_by_id, evidence_by_event, tuples_by_event, max_text_chars):
    rows = []

    for event_id in sorted(events_by_id.keys(), key=natural_event_sort_key):
        event = events_by_id[event_id]
        evidence_candidates = [
            compact_evidence(ev, max_text_chars)
            for ev in evidence_by_event.get(event_id, [])
        ]
        gold_tuples = [
            compact_tuple(tup)
            for tup in tuples_by_event.get(event_id, [])
        ]

        rows.append({
            "task_id": f"TI_{safe_id(event_id)}",
            "task_type": "tuple_identification",
            "event_id": event_id,
            "input": {
                "event": compact_event(event),
                "evidence_candidates": evidence_candidates,
            },
            "output": {
                "gold_tuples": gold_tuples,
            },
            "metadata": {
                "evidence_count": len(evidence_candidates),
                "gold_tuple_count": len(gold_tuples),
            },
        })

    return rows


def build_evidence_support_classification(
    events_by_id,
    evidence_by_id,
    evidence_by_event,
    tuples_by_event,
    max_text_chars,
    negative_per_tuple,
    rng,
):
    rows = []
    label_counter = Counter()

    for event_id in sorted(events_by_id.keys(), key=natural_event_sort_key):
        event = events_by_id[event_id]
        event_evidence = evidence_by_event.get(event_id, [])
        event_evidence_ids = [get_evidence_id(ev) for ev in event_evidence if get_evidence_id(ev)]

        for tup in tuples_by_event.get(event_id, []):
            candidate_id = tup.get("candidate_id", "")
            gold_eids = get_evidence_ids(tup)
            gold_eid_set = set(gold_eids)
            support_label = tup.get("support_label", "")

            for evidence_id in gold_eids:
                ev = evidence_by_id.get(evidence_id)
                if not ev:
                    continue

                task_id = f"ESC_{safe_id(candidate_id)}_{safe_id(evidence_id)}"
                row = {
                    "task_id": task_id,
                    "task_type": "evidence_support_classification",
                    "event_id": event_id,
                    "candidate_id": candidate_id,
                    "evidence_id": evidence_id,
                    "input": {
                        "event": compact_event(event),
                        "tuple_claim": compact_tuple_claim(tup),
                        "evidence": compact_evidence(ev, max_text_chars),
                    },
                    "output": {
                        "support_label": support_label,
                        "is_gold_evidence": True,
                    },
                    "metadata": {
                        "sample_type": "positive",
                        "gold_evidence_ids": gold_eids,
                    },
                }
                rows.append(row)
                label_counter[support_label] += 1

            negative_pool = [eid for eid in event_evidence_ids if eid not in gold_eid_set]
            if negative_per_tuple > 0 and negative_pool:
                sample_size = min(negative_per_tuple, len(negative_pool))
                sampled = rng.sample(negative_pool, sample_size)

                for idx, evidence_id in enumerate(sampled, start=1):
                    ev = evidence_by_id.get(evidence_id)
                    if not ev:
                        continue

                    task_id = f"ESC_{safe_id(candidate_id)}_NEG_{idx}_{safe_id(evidence_id)}"
                    row = {
                        "task_id": task_id,
                        "task_type": "evidence_support_classification",
                        "event_id": event_id,
                        "candidate_id": candidate_id,
                        "evidence_id": evidence_id,
                        "input": {
                            "event": compact_event(event),
                            "tuple_claim": compact_tuple_claim(tup),
                            "evidence": compact_evidence(ev, max_text_chars),
                        },
                        "output": {
                            "support_label": "not_enough_info",
                            "is_gold_evidence": False,
                        },
                        "metadata": {
                            "sample_type": "negative_same_event",
                            "gold_evidence_ids": gold_eids,
                        },
                    }
                    rows.append(row)
                    label_counter["not_enough_info"] += 1

    return rows, dict(label_counter)


def build_chain_construction(events_by_id, evidence_by_event, chains_by_event, max_text_chars):
    rows = []

    for event_id in sorted(events_by_id.keys(), key=natural_event_sort_key):
        event = events_by_id[event_id]
        evidence_candidates = [
            compact_evidence(ev, max_text_chars)
            for ev in evidence_by_event.get(event_id, [])
        ]
        gold_chains = [
            compact_chain(chain)
            for chain in chains_by_event.get(event_id, [])
        ]

        rows.append({
            "task_id": f"CC_{safe_id(event_id)}",
            "task_type": "chain_construction",
            "event_id": event_id,
            "input": {
                "event": compact_event(event),
                "evidence_candidates": evidence_candidates,
            },
            "output": {
                "gold_chains": gold_chains,
            },
            "metadata": {
                "evidence_count": len(evidence_candidates),
                "gold_chain_count": len(gold_chains),
            },
        })

    return rows


def build_event_split(event_ids, train_ratio, dev_ratio, seed):
    ids = list(event_ids)
    rng = random.Random(seed)
    rng.shuffle(ids)

    n = len(ids)
    n_train = int(round(n * train_ratio))
    n_dev = int(round(n * dev_ratio))

    if n_train + n_dev > n:
        n_dev = max(0, n - n_train)

    train = ids[:n_train]
    dev = ids[n_train:n_train + n_dev]
    test = ids[n_train + n_dev:]

    return {
        "train": sorted(train, key=natural_event_sort_key),
        "dev": sorted(dev, key=natural_event_sort_key),
        "test": sorted(test, key=natural_event_sort_key),
    }


def write_splits(output_dir, filename_prefix, rows, split, backup_existing=False):
    rows_by_split = {"train": [], "dev": [], "test": []}

    for row in rows:
        event_id = row.get("event_id")
        assigned = None
        for split_name, event_ids in split.items():
            if event_id in event_ids:
                assigned = split_name
                break
        if assigned:
            rows_by_split[assigned].append(row)

    for split_name, split_rows in rows_by_split.items():
        path = Path(output_dir) / "splits" / split_name / f"{filename_prefix}.jsonl"
        write_jsonl(path, split_rows, backup_existing=backup_existing)

    return {k: len(v) for k, v in rows_by_split.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--tuples", required=True)
    parser.add_argument("--chains", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--negative-per-tuple", type=int, default=2)
    parser.add_argument("--max-text-chars", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--make-splits", action="store_true")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--dev-ratio", type=float, default=0.1)
    parser.add_argument("--backup-existing", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)

    events = read_jsonl(args.events)
    evidence = read_jsonl(args.evidence)
    tuples = read_jsonl(args.tuples)
    chains = read_jsonl(args.chains)

    events_by_id, evidence_by_id, evidence_by_event, tuples_by_event, chains_by_event = build_indices(
        events, evidence, tuples, chains
    )

    validation = validate_refs(tuples, chains, evidence_by_id)

    tuple_identification_rows = build_tuple_identification(
        events_by_id, evidence_by_event, tuples_by_event, args.max_text_chars
    )

    evidence_support_rows, evidence_support_label_dist = build_evidence_support_classification(
        events_by_id=events_by_id,
        evidence_by_id=evidence_by_id,
        evidence_by_event=evidence_by_event,
        tuples_by_event=tuples_by_event,
        max_text_chars=args.max_text_chars,
        negative_per_tuple=args.negative_per_tuple,
        rng=rng,
    )

    chain_construction_rows = build_chain_construction(
        events_by_id, evidence_by_event, chains_by_event, args.max_text_chars
    )

    tuple_identification_path = output_dir / "tuple_identification.jsonl"
    evidence_support_path = output_dir / "evidence_support_classification.jsonl"
    chain_construction_path = output_dir / "chain_construction.jsonl"
    statistics_path = output_dir / "benchmark_statistics.json"
    manifest_path = output_dir / "benchmark_manifest.json"

    write_jsonl(tuple_identification_path, tuple_identification_rows, args.backup_existing)
    write_jsonl(evidence_support_path, evidence_support_rows, args.backup_existing)
    write_jsonl(chain_construction_path, chain_construction_rows, args.backup_existing)

    event_ids = sorted(events_by_id.keys(), key=natural_event_sort_key)
    split_info = None
    split_row_counts = None

    if args.make_splits:
        split_info = build_event_split(event_ids, args.train_ratio, args.dev_ratio, args.seed)
        split_row_counts = {
            "tuple_identification": write_splits(
                output_dir, "tuple_identification", tuple_identification_rows, split_info, args.backup_existing
            ),
            "evidence_support_classification": write_splits(
                output_dir, "evidence_support_classification", evidence_support_rows, split_info, args.backup_existing
            ),
            "chain_construction": write_splits(
                output_dir, "chain_construction", chain_construction_rows, split_info, args.backup_existing
            ),
        }

    statistics = {
        "source_files": {
            "events": str(args.events),
            "evidence": str(args.evidence),
            "tuples": str(args.tuples),
            "chains": str(args.chains),
        },
        "input_counts": {
            "events": len(events),
            "event_ids": len(events_by_id),
            "evidence": len(evidence),
            "tuples": len(tuples),
            "chains": len(chains),
        },
        "task_counts": {
            "tuple_identification": len(tuple_identification_rows),
            "evidence_support_classification": len(evidence_support_rows),
            "chain_construction": len(chain_construction_rows),
        },
        "evidence_support_label_distribution": evidence_support_label_dist,
        "negative_sampling": {
            "negative_per_tuple": args.negative_per_tuple,
            "seed": args.seed,
            "strategy": "same-event evidence not listed in tuple.evidence_ids",
        },
        "validation": {
            "missing_tuple_evidence_refs_count": len(validation["missing_tuple_evidence_refs"]),
            "missing_chain_evidence_refs_count": len(validation["missing_chain_evidence_refs"]),
            "missing_tuple_evidence_refs": validation["missing_tuple_evidence_refs"][:50],
            "missing_chain_evidence_refs": validation["missing_chain_evidence_refs"][:50],
        },
        "splits": split_info,
        "split_row_counts": split_row_counts,
    }

    manifest = {
        "benchmark_version": output_dir.name,
        "created_by": "scripts/build_benchmark_tasks.py",
        "outputs": {
            "tuple_identification": str(tuple_identification_path),
            "evidence_support_classification": str(evidence_support_path),
            "chain_construction": str(chain_construction_path),
            "benchmark_statistics": str(statistics_path),
        },
        "task_definitions": {
            "tuple_identification": "Given an event and candidate evidence records, identify all gold SOA tuples.",
            "evidence_support_classification": "Given an event, a tuple claim, and one evidence record, classify evidence support.",
            "chain_construction": "Given an event and candidate evidence records, construct gold event chains.",
        },
        "notes": [
            "Tuple identification and chain construction are event-level tasks.",
            "Evidence support classification contains gold positive tuple-evidence pairs and optional same-event negative samples.",
            "Source files are not modified by this script.",
        ],
    }

    write_json(statistics_path, statistics, args.backup_existing)
    write_json(manifest_path, manifest, args.backup_existing)

    print("=== Benchmark Task Construction ===")
    print(f"Events:                         {len(events_by_id)}")
    print(f"Evidence:                       {len(evidence)}")
    print(f"Gold tuples:                    {len(tuples)}")
    print(f"Gold chains:                    {len(chains)}")
    print(f"Tuple identification rows:      {len(tuple_identification_rows)}")
    print(f"Evidence support rows:          {len(evidence_support_rows)}")
    print(f"Chain construction rows:        {len(chain_construction_rows)}")
    print(f"Missing tuple evidence refs:    {len(validation['missing_tuple_evidence_refs'])}")
    print(f"Missing chain evidence refs:    {len(validation['missing_chain_evidence_refs'])}")
    print(f"Output dir:                     {output_dir}")

    if args.make_splits:
        print("Splits:")
        for split_name, ids in split_info.items():
            print(f"  {split_name}: {len(ids)} events")


if __name__ == "__main__":
    main()
