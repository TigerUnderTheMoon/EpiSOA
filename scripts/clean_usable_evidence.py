"""Clean canonical evidence using local usable-text checks."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from episoa.data.loader import read_jsonl, read_typed_jsonl, write_jsonl
from episoa.data.schema import EvidenceRecord

from scripts.backfill_canonical_evidence_fulltext import (
    build_event_terms,
    event_rows_for_ids,
    is_binary_response,
    normalize_text,
    unusable_text_reason,
    validate_output,
)


DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_AUDIT_ROOT = Path("data/pubevent_soa_lite/interim")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean canonical evidence by local usable-text checks.")
    parser.add_argument("--input", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--output", default=None, help="Output JSONL. Defaults to input when --in-place is set.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--audit-root", default=str(DEFAULT_AUDIT_ROOT))
    parser.add_argument("--threshold", type=int, default=15)
    parser.add_argument("--in-place", action="store_true", help="Backup and replace input after validation.")
    parser.add_argument("--dry-run", action="store_true", help="Write audit artifacts only; do not replace input.")
    return parser


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    if output_path == input_path and not args.in_place and not args.dry_run:
        raise SystemExit("Refusing to overwrite input without --in-place or --dry-run.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    audit_dir = Path(args.audit_root) / f"usable_evidence_clean_{timestamp}"
    audit_dir.mkdir(parents=True, exist_ok=True)

    rows = read_jsonl(input_path)
    event_terms = build_event_terms(read_jsonl(args.events) if Path(args.events).exists() else [])

    kept: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    repaired: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for row in rows:
        decision = clean_row(row, event_terms.get(str(row.get("event_id") or ""), []))
        status_counts[decision["status"]] += 1
        if decision["status"] in {"kept", "repaired_from_legacy_text"}:
            kept.append(decision["row"])
            if decision["status"] == "repaired_from_legacy_text":
                repaired.append(repair_audit_row(row, decision["row"], decision["reason"]))
        else:
            reason_counts[decision["reason"]] += 1
            deleted.append(delete_audit_row(row, decision["reason"]))

    per_event_counts = dict(sorted(Counter(str(row.get("event_id") or "") for row in kept).items()))
    below_threshold = [
        {"event_id": event_id, "usable_evidence_count": count}
        for event_id, count in per_event_counts.items()
        if count < int(args.threshold)
    ]
    for event_id in events_with_no_evidence(args.events, per_event_counts):
        below_threshold.append({"event_id": event_id, "usable_evidence_count": 0})

    write_jsonl(audit_dir / "cleaned_evidence.preview.jsonl", kept)
    write_jsonl(audit_dir / "deleted_evidence.jsonl", deleted)
    write_jsonl(audit_dir / "repaired_evidence.jsonl", repaired)
    write_jsonl(audit_dir / "events_below_threshold.jsonl", event_rows_for_ids(Path(args.events), below_threshold))

    report = {
        "input": str(input_path),
        "output": str(output_path),
        "dry_run": bool(args.dry_run),
        "in_place": bool(args.in_place),
        "processed_rows": len(rows),
        "kept_rows": len(kept),
        "deleted_rows": len(deleted),
        "repaired_rows": len(repaired),
        "status_counts": dict(status_counts),
        "delete_reason_counts": dict(reason_counts),
        "threshold": int(args.threshold),
        "per_event_usable_evidence_count": per_event_counts,
        "events_below_threshold": sorted(below_threshold, key=lambda row: (row["usable_evidence_count"], row["event_id"])),
        "audit_dir": str(audit_dir),
    }
    write_json(audit_dir / "usable_evidence_clean_report.json", report)

    if args.dry_run:
        print(f"dry-run wrote audit artifacts to {audit_dir}")
        return 0

    validate_output(kept)
    temp_path = output_path.with_name(output_path.name + f".tmp_usable_clean_{timestamp}")
    write_jsonl(temp_path, kept)
    read_typed_jsonl(temp_path, EvidenceRecord)

    if args.in_place:
        backup_path = input_path.with_name(input_path.name + f".bak_before_usable_clean_{timestamp}")
        shutil.copy2(input_path, backup_path)
        temp_path.replace(input_path)
        report["backup_path"] = str(backup_path)
        report["replaced_path"] = str(input_path)
    else:
        temp_path.replace(output_path)
        report["written_path"] = str(output_path)
    write_json(audit_dir / "usable_evidence_clean_report.json", report)
    print(f"wrote {output_path}")
    print(f"audit_dir: {audit_dir}")
    return 0


def clean_row(row: dict[str, Any], event_terms: list[str]) -> dict[str, Any]:
    content_type = str(row.get("fulltext_content_type") or "")
    if is_binary_response(b"", content_type):
        return {"status": "deleted", "reason": "binary_content_type"}

    text = normalize_text(str(row.get("text") or ""))
    reason = unusable_text_reason(text, event_terms)
    if not reason:
        output = dict(row)
        output["usable_clean_status"] = "ok"
        output["usable_clean_reason"] = ""
        output["usable_text_chars"] = len(text)
        return {"status": "kept", "row": output, "reason": ""}

    legacy_text = normalize_text(str(row.get("legacy_text") or ""))
    legacy_reason = unusable_text_reason(legacy_text, event_terms)
    if reason != "binary_content_type" and legacy_text and not legacy_reason:
        output = dict(row)
        output["unusable_fulltext"] = text
        output["text"] = legacy_text
        output["usable_clean_status"] = "repaired_from_legacy_text"
        output["usable_clean_reason"] = reason
        output["usable_text_chars"] = len(legacy_text)
        return {"status": "repaired_from_legacy_text", "row": output, "reason": reason}

    return {"status": "deleted", "reason": reason}


def delete_audit_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "evidence_id": row.get("evidence_id"),
        "event_id": row.get("event_id"),
        "url": row.get("url"),
        "source": row.get("source"),
        "source_type": row.get("source_type"),
        "delete_reason": reason,
        "text_chars": len(str(row.get("text") or "")),
        "content_type": row.get("fulltext_content_type"),
        "text_preview": str(row.get("text") or "")[:300],
    }


def repair_audit_row(original: dict[str, Any], repaired: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "evidence_id": original.get("evidence_id"),
        "event_id": original.get("event_id"),
        "url": original.get("url"),
        "repair_reason": reason,
        "old_text_chars": len(str(original.get("text") or "")),
        "new_text_chars": len(str(repaired.get("text") or "")),
    }


def events_with_no_evidence(events_path: str | Path, per_event_counts: dict[str, int]) -> list[str]:
    path = Path(events_path)
    if not path.exists():
        return []
    event_ids = [str(row.get("event_id") or "") for row in read_jsonl(path)]
    return [event_id for event_id in event_ids if event_id and event_id not in per_event_counts]


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
