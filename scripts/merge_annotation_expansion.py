"""Merge annotation expansion delta files into gold annotation.

Safety protocol:
  1. Runs audit_delta check first (refuses to merge if issues exist)
  2. Writes merged output to a NEW file (not overwriting original gold)
  3. Only overwrites original gold when --commit flag is set
  4. Always backs up original gold files before overwriting

IMPORTANT: Uses evidence_v3_repaired_plus_low37.jsonl as canonical evidence.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl

CANONICAL_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_ANNOTATION_DIR = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37"
)
DEFAULT_TUPLES = DEFAULT_ANNOTATION_DIR / "llm_gold_tuples.jsonl"
DEFAULT_CHAINS = DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains.jsonl"
DEFAULT_DELTA_TUPLES = DEFAULT_ANNOTATION_DIR / "llm_gold_tuples_expansion_delta.jsonl"
DEFAULT_DELTA_CHAINS = DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains_expansion_delta.jsonl"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return merge(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge annotation expansion deltas into gold annotation "
                    "(with safety gates)."
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
    parser.add_argument("--commit", action="store_true",
                        help="Overwrite original gold files (requires audit pass)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for merged output files "
                             "(default: same as input annotation directory)")
    parser.add_argument("--skip-audit", action="store_true",
                        help="Skip pre-merge audit (NOT recommended)")
    parser.add_argument("--audit-script", default=None,
                        help="Path to audit_annotation_expansion_delta.py")
    return parser


def merge(args: argparse.Namespace) -> int:
    tuples_path = Path(args.tuples)
    chains_path = Path(args.chains)
    delta_tuples_path = Path(args.delta_tuples)
    delta_chains_path = Path(args.delta_chains)
    evidence_path = Path(args.evidence)

    for fp, label in [
        (tuples_path, "existing tuples"),
        (chains_path, "existing chains"),
        (delta_tuples_path, "delta tuples"),
        (delta_chains_path, "delta chains"),
    ]:
        if not fp.exists():
            print(f"ERROR: {label} file not found: {fp}")
            return 1

    existing_tuples = read_jsonl(str(tuples_path))
    existing_chains = read_jsonl(str(chains_path))
    delta_tuples = read_jsonl(str(delta_tuples_path))
    delta_chains = read_jsonl(str(delta_chains_path))

    if not delta_tuples and not delta_chains:
        print("Delta files are empty. Nothing to merge.")
        return 1

    # ---- pre-merge audit ----
    if not args.skip_audit:
        audit_ok, audit_output = _run_audit(args, tuples_path, chains_path,
                                              delta_tuples_path, delta_chains_path,
                                              evidence_path)
        if not audit_ok:
            print("\nERROR: Pre-merge audit failed. Fix issues before merging.")
            if audit_output:
                print("Audit output:\n" + audit_output[:2000])
            return 1
        print("Pre-merge audit PASSED.")
    else:
        print("WARNING: Skipping pre-merge audit (--skip-audit).")

    # ---- build merged records ----
    existing_cids = {t["candidate_id"] for t in existing_tuples}
    existing_chain_cids = {c.get("candidate_chain_id", "") for c in existing_chains}
    existing_short_cids = {c.get("chain_id", "") for c in existing_chains if c.get("chain_id")}

    merged_tuples = list(existing_tuples)
    merged_chains = list(existing_chains)
    skipped_tuples = 0
    skipped_chains = 0

    for t in delta_tuples:
        cid = t.get("candidate_id", "")
        if cid in existing_cids:
            skipped_tuples += 1
            continue
        existing_cids.add(cid)
        merged_tuples.append(t)

    for c in delta_chains:
        ccid = c.get("candidate_chain_id", "")
        scid = c.get("chain_id", "")
        if ccid in existing_chain_cids:
            skipped_chains += 1
            continue
        if scid and scid in existing_short_cids:
            skipped_chains += 1
            continue
        if scid and scid in existing_short_cids:
            skipped += 1
            continue
        existing_chain_cids.add(ccid)
        if scid:
            existing_short_cids.add(scid)
        merged_chains.append(c)

    output_dir = Path(args.output_dir) if args.output_dir else tuples_path.parent

    # ---- write merged files first ----
    merged_tuples_path = output_dir / "llm_gold_tuples_merged.jsonl"
    merged_chains_path = output_dir / "llm_gold_event_chains_merged.jsonl"

    write_jsonl(str(merged_tuples_path), merged_tuples)
    write_jsonl(str(merged_chains_path), merged_chains)

    print(f"\nMerged tuples: {len(merged_tuples)} ({len(delta_tuples) - skipped_tuples} new, "
          f"{skipped_tuples} skipped as duplicates)")
    print(f"Merged chains: {len(merged_chains)} ({len(delta_chains) - skipped_chains} new, "
          f"{skipped_chains} skipped as duplicates)")

    t_counts = Counter(t["event_id"] for t in merged_tuples)
    c_counts = Counter(c["event_id"] for c in merged_chains)
    all_eids = sorted(set(t_counts.keys()) | set(c_counts.keys()))

    low_t = [(eid, c) for eid, c in t_counts.items() if c < 3]
    low_c = [(eid, c) for eid, c in c_counts.items() if c < 2]
    if low_t:
        print(f"\nWARNING: {len(low_t)} events still have <3 tuples after merge:")
        for eid, c in low_t:
            print(f"  {eid}: {c} tuples")
    if low_c:
        print(f"\nWARNING: {len(low_c)} events still have <2 chains after merge:")
        for eid, c in low_c:
            print(f"  {eid}: {c} chains")

    print(f"\nMerged files written:")
    print(f"  Tuples: {merged_tuples_path}")
    print(f"  Chains: {merged_chains_path}")

    # ---- commit: overwrite original gold files ----
    if args.commit:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        for orig_path, merged_path in [
            (tuples_path, merged_tuples_path),
            (chains_path, merged_chains_path),
        ]:
            backup_path = orig_path.with_suffix(f".jsonl.bak_{timestamp}")
            shutil.copy2(orig_path, backup_path)
            print(f"Backed up {orig_path.name} → {backup_path.name}")

            shutil.copy2(merged_path, orig_path)
            print(f"Committed merged → {orig_path.name}")

        print("\nMerge committed to original gold files.")
    else:
        print("\nMerged files are staged but NOT committed to original gold.")
        print("Review merged files, then run with --commit to overwrite originals.")

    return 0


def _run_audit(
    args: argparse.Namespace,
    tuples_path: Path,
    chains_path: Path,
    delta_tuples_path: Path,
    delta_chains_path: Path,
    evidence_path: Path,
) -> tuple[bool, str]:
    audit_script = args.audit_script or (
        Path(__file__).parent / "audit_annotation_expansion_delta.py"
    )
    if not Path(audit_script).exists():
        print(f"ERROR: audit script not found: {audit_script}")
        return False, ""

    cmd = [
        sys.executable, str(audit_script),
        "--tuples", str(tuples_path),
        "--chains", str(chains_path),
        "--delta-tuples", str(delta_tuples_path),
        "--delta-chains", str(delta_chains_path),
        "--evidence", str(evidence_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        print(f"ERROR running audit: {e}")
        return False, str(e)


if __name__ == "__main__":
    raise SystemExit(main())
