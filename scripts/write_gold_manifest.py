"""Generate or update gold_manifest.json for a gold annotation dataset.

Records metadata about the gold annotation:
  - version label
  - canonical evidence file path
  - gold tuple and chain file paths
  - row counts
  - quality status (from audit)
  - notes

IMPORTANT: references evidence_v3_repaired_plus_low37.jsonl as canonical evidence.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from episoa.data.loader import read_jsonl

DEFAULT_ANNOTATION_DIR = Path(
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37"
)
CANONICAL_EVIDENCE_REL = "data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return write_manifest(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or update gold_manifest.json for a gold annotation dataset."
    )
    parser.add_argument("--tuples", default=str(DEFAULT_ANNOTATION_DIR / "llm_gold_tuples.jsonl"),
                        help="Path to gold tuples JSONL")
    parser.add_argument("--chains", default=str(DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains.jsonl"),
                        help="Path to gold chains JSONL")
    parser.add_argument("--evidence", default=CANONICAL_EVIDENCE_REL,
                        help="Path to canonical evidence JSONL")
    parser.add_argument("--version", default=None,
                        help="Version label (default: auto-generated from timestamp)")
    parser.add_argument("--output", default=None,
                        help="Output path for manifest (default: annotation dir)")
    parser.add_argument("--quality-status", default=None,
                        help='Path to audit report JSON to extract quality_status from')
    parser.add_argument("--notes", default=None, nargs="*",
                        help="Additional notes to append")
    return parser


def write_manifest(args: argparse.Namespace) -> int:
    tuples_path = Path(args.tuples)
    chains_path = Path(args.chains)

    if not tuples_path.exists():
        print(f"ERROR: tuples file not found: {tuples_path}")
        return 1
    if not chains_path.exists():
        print(f"ERROR: chains file not found: {chains_path}")
        return 1

    tuples = read_jsonl(str(tuples_path))
    chains = read_jsonl(str(chains_path))

    version = args.version or datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")

    quality_status = _default_quality_status()
    if args.quality_status:
        qs_path = Path(args.quality_status)
        if qs_path.exists():
            audit_data = json.loads(qs_path.read_text(encoding="utf-8"))
            if "checks" in audit_data:
                quality_status = audit_data["checks"]

    notes = [
        "Use evidence_v3_repaired_plus_low37.jsonl as canonical evidence namespace.",
        "Do not audit this gold version against evidence_filtered.jsonl.",
    ]
    if args.notes:
        notes.extend(args.notes)

    manifest = {
        "version": version,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canonical_evidence_file": args.evidence,
        "gold_tuple_file": str(tuples_path),
        "gold_chain_file": str(chains_path),
        "tuple_rows": len(tuples),
        "chain_rows": len(chains),
        "quality_status": quality_status,
        "notes": notes,
    }

    output_path = Path(args.output) if args.output else (
        tuples_path.parent / "gold_manifest.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Manifest written to: {output_path}")
    print(f"  version:            {manifest['version']}")
    print(f"  evidence:           {manifest['canonical_evidence_file']}")
    print(f"  gold_tuples:        {manifest['gold_tuple_file']} ({manifest['tuple_rows']} rows)")
    print(f"  gold_chains:        {manifest['gold_chain_file']} ({manifest['chain_rows']} rows)")
    return 0


def _default_quality_status() -> dict[str, str]:
    return {
        "event_coverage": "UNKNOWN",
        "tuple_count_min_ge_3": "UNKNOWN",
        "chain_count_min_ge_2": "UNKNOWN",
        "candidate_id_duplicates": "UNKNOWN",
        "chain_id_duplicates": "UNKNOWN",
        "missing_chain_ids": "UNKNOWN",
        "invalid_sentiments": "UNKNOWN",
        "invalid_support_labels": "UNKNOWN",
        "missing_evidence_refs": "UNKNOWN",
        "missing_source_type": "UNKNOWN",
    }


if __name__ == "__main__":
    raise SystemExit(main())
