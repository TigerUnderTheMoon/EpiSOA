#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Export LLM preannotation files as an explicit silver benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ANNOTATION_DIR = Path("data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37")
DEFAULT_OUTPUT_DIR = Path("data/pubevent_soa_lite/silver_v1")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = export_silver_benchmark(
        tuples_path=Path(args.tuples),
        chains_path=Path(args.chains),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export current LLM preannotation files as silver_v1.")
    parser.add_argument(
        "--tuples",
        default=str(DEFAULT_ANNOTATION_DIR / "llm_gold_tuples.jsonl"),
        help="Input LLM-preannotation tuple JSONL.",
    )
    parser.add_argument(
        "--chains",
        default=str(DEFAULT_ANNOTATION_DIR / "llm_gold_event_chains.jsonl"),
        help="Input LLM-preannotation event-chain JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for silver_tuples_v1.jsonl, silver_event_chains_v1.jsonl, and manifest.",
    )
    return parser


def export_silver_benchmark(*, tuples_path: Path, chains_path: Path, output_dir: Path) -> dict[str, Any]:
    before = {path: file_fingerprint(path) for path in (tuples_path, chains_path)}
    tuples = read_jsonl(tuples_path)
    chains = read_jsonl(chains_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    tuples_out = output_dir / "silver_tuples_v1.jsonl"
    chains_out = output_dir / "silver_event_chains_v1.jsonl"
    manifest_out = output_dir / "silver_manifest_v1.json"
    write_jsonl(tuples_out, tuples)
    write_jsonl(chains_out, chains)

    after = {path: file_fingerprint(path) for path in (tuples_path, chains_path)}
    original_files_modified = before != after
    manifest = {
        "dataset_name": "pubevent_soa_lite_silver_v1",
        "dataset_level": "silver",
        "source": "llm_preannotation",
        "human_verified": False,
        "auto_reviewer_accept_all": True,
        "original_files_modified": original_files_modified,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_files": {
            "tuples": str(tuples_path),
            "event_chains": str(chains_path),
        },
        "input_fingerprints": {
            str(path): before[path] for path in before
        },
        "outputs": {
            "silver_tuples": str(tuples_out),
            "silver_event_chains": str(chains_out),
            "silver_manifest": str(manifest_out),
        },
        "counts": {
            "silver_tuples": len(tuples),
            "silver_event_chains": len(chains),
            "events_with_tuples": len({str(row.get("event_id")) for row in tuples if row.get("event_id")}),
            "events_with_chains": len({str(row.get("event_id")) for row in chains if row.get("event_id")}),
        },
        "notes": [
            "The source files are LLM preannotation outputs, not final human gold.",
            "This script copies records to a new silver_v1 namespace and never writes to original llm_gold_* files.",
        ],
    }
    write_json(manifest_out, manifest)
    if original_files_modified:
        raise RuntimeError("Input files changed during silver export; aborting.")
    return manifest


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    backup_existing(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    backup_existing(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def backup_existing(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{timestamp}")
    shutil.copy2(path, backup)


def file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = path.read_bytes()
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


if __name__ == "__main__":
    raise SystemExit(main())
