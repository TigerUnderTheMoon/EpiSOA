"""Normalize chain_id field in gold event chains JSONL.

Generates deterministic chain_id for records missing it:
  Format: CHAIN_{event_id}_{序号}

Checks for duplicate chain_ids and auto-repairs if found.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl

DEFAULT_CHAINS = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/"
    "llm_gold_event_chains.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return normalize_chain_ids(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize chain_id field in gold event chains JSONL."
    )
    parser.add_argument("--input", default=str(DEFAULT_CHAINS),
                        help="Path to llm_gold_event_chains.jsonl")
    parser.add_argument("--output", default=None,
                        help="Output path (default: overwrite input after backup)")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip automatic backup of original file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report issues without writing")
    return parser


def normalize_chain_ids(args: argparse.Namespace) -> int:
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        return 1

    chains = read_jsonl(str(input_path))
    if not chains:
        print("No chain records found.")
        return 1

    existing_chain_ids: set[str] = set()
    missing = 0
    duplicates: dict[str, int] = {}
    all_chain_ids: list[str] = []

    for c in chains:
        cid = c.get("chain_id", "")
        if cid:
            existing_chain_ids.add(cid)
            all_chain_ids.append(cid)
        else:
            all_chain_ids.append("")

    dup_counter = Counter(all_chain_ids)
    if "" in dup_counter:
        del dup_counter[""]
    duplicates = {k: v for k, v in dup_counter.items() if v > 1}

    for c in chains:
        if not c.get("chain_id"):
            missing += 1

    print(f"Total chains: {len(chains)}")
    print(f"Missing chain_id: {missing}")
    print(f"Duplicate chain_ids: {len(duplicates)}")
    if duplicates:
        for cid, count in duplicates.items():
            print(f"  {cid}: {count} occurrences")

    if missing == 0 and not duplicates:
        print("All chain_ids are present and unique. Nothing to do.")
        return 0

    if args.dry_run:
        print("\n[DRY RUN] Would generate chain_ids for {missing} missing records.")
        return 0

    event_counters: dict[str, int] = defaultdict(int)
    used_chain_ids: set[str] = set()
    for c in chains:
        cid = c.get("chain_id", "")
        if cid and cid not in used_chain_ids:
            used_chain_ids.add(cid)

    for c in chains:
        if c.get("chain_id"):
            continue
        event_id = c["event_id"]
        while True:
            event_counters[event_id] += 1
            seq = event_counters[event_id]
            new_id = f"CHAIN_{event_id}_{seq:03d}"
            if new_id not in used_chain_ids:
                used_chain_ids.add(new_id)
                c["chain_id"] = new_id
                break

    if duplicates:
        _repair_duplicates(chains, duplicates)

    output_path = Path(args.output) if args.output else input_path

    if not args.no_backup and output_path == input_path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = input_path.with_suffix(f".jsonl.bak_{timestamp}")
        shutil.copy2(input_path, backup_path)
        print(f"Backed up original to: {backup_path}")

    write_jsonl(str(output_path), chains)
    print(f"Wrote {len(chains)} chain records to {output_path}")
    return 0


def _repair_duplicates(
    chains: list[dict[str, Any]],
    duplicates: dict[str, int],
) -> None:
    event_counters: dict[str, int] = defaultdict(int)
    used_ids: set[str] = set()
    for c in chains:
        cid = c.get("chain_id", "")
        if cid and cid not in duplicates:
            used_ids.add(cid)

    seen: set[str] = set()
    for c in chains:
        cid = c.get("chain_id", "")
        if cid in duplicates:
            if cid in seen:
                event_id = c["event_id"]
                while True:
                    event_counters[event_id] += 1
                    seq = event_counters[event_id]
                    new_id = f"CHAIN_{event_id}_{seq:03d}"
                    if new_id not in used_ids:
                        used_ids.add(new_id)
                        c["chain_id"] = new_id
                        break
            else:
                seen.add(cid)


if __name__ == "__main__":
    raise SystemExit(main())
