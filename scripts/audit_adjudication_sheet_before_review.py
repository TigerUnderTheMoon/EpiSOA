#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit adjudication CSV sheets before human review starts."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HUMAN_DIR = Path("data/pubevent_soa_lite/human_gold_v1")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/audit_full_pipeline")

REQUIRED_TUPLE_FIELDS = [
    "event_id",
    "tuple_id",
    "stakeholder",
    "opinion",
    "sentiment",
    "rationale",
    "event_chain",
    "evidence_ids",
    "evidence_texts",
    "evidence_source_types",
    "review_decision",
    "revised_stakeholder",
    "revised_opinion",
    "revised_sentiment",
    "revised_rationale",
    "revised_evidence_ids",
    "reviewer_note",
    "reviewer_id",
    "adjudication_status",
]
REQUIRED_CHAIN_FIELDS = [
    "event_id",
    "chain_id",
    "event_chain",
    "evidence_ids",
    "evidence_texts",
    "evidence_source_types",
    "review_decision",
    "revised_event_chain",
    "revised_evidence_ids",
    "reviewer_note",
    "reviewer_id",
    "adjudication_status",
]
VALID_REVIEW_DECISIONS = {"accept", "revise", "drop", "add_missing", "uncertain"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_adjudication_sheets(
        tuple_sheet=Path(args.tuple_sheet),
        chain_sheet=Path(args.chain_sheet),
        evidence_path=Path(args.evidence),
        events_path=Path(args.events),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready_for_human_review"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pre-review audit for human adjudication sheets.")
    parser.add_argument("--tuple-sheet", default=str(DEFAULT_HUMAN_DIR / "human_tuple_adjudication_sheet.csv"))
    parser.add_argument("--chain-sheet", default=str(DEFAULT_HUMAN_DIR / "human_chain_adjudication_sheet.csv"))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def audit_adjudication_sheets(
    *,
    tuple_sheet: Path,
    chain_sheet: Path,
    evidence_path: Path,
    events_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    tuple_rows, tuple_fields = read_csv_with_fields(tuple_sheet)
    chain_rows, chain_fields = read_csv_with_fields(chain_sheet)
    evidence = read_jsonl(evidence_path)
    events = read_jsonl(events_path)
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}
    event_ids = {str(row.get("event_id")) for row in events if row.get("event_id")}

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    check_required_fields("tuple", tuple_fields, REQUIRED_TUPLE_FIELDS, errors)
    check_required_fields("chain", chain_fields, REQUIRED_CHAIN_FIELDS, errors)
    audit_tuple_rows(tuple_rows, event_ids, evidence_by_id, errors, warnings)
    audit_chain_rows(chain_rows, event_ids, evidence_by_id, errors, warnings)

    report = {
        "ready_for_human_review": not errors,
        "total_errors": len(errors),
        "total_warnings": len(warnings),
        "error_counts": dict(Counter(item["check"] for item in errors)),
        "warning_counts": dict(Counter(item["check"] for item in warnings)),
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "tuple_rows": len(tuple_rows),
            "chain_rows": len(chain_rows),
            "canonical_evidence_records": len(evidence),
            "events": len(events),
        },
        "inputs": {
            "tuple_sheet": str(tuple_sheet),
            "chain_sheet": str(chain_sheet),
            "canonical_evidence": str(evidence_path),
            "events": str(events_path),
        },
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "adjudication_sheet_pre_review_audit.json", report)
    write_text(output_dir / "adjudication_sheet_pre_review_audit.md", render_markdown(report))
    return report


def audit_tuple_rows(
    rows: list[dict[str, str]],
    event_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    seen_tuple_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        row_id = row.get("tuple_id") or f"row_{index}"
        event_id = str(row.get("event_id") or "")
        tuple_id = str(row.get("tuple_id") or "")
        if not event_id or event_id not in event_ids:
            errors.append(item("tuple_event_id_exists", row_id, f"unknown event_id {event_id}"))
        if not tuple_id:
            errors.append(item("tuple_id_nonempty", row_id, "tuple_id is empty"))
        elif tuple_id in seen_tuple_ids:
            errors.append(item("tuple_id_unique", row_id, f"duplicate tuple_id {tuple_id}"))
        seen_tuple_ids.add(tuple_id)
        check_default_uncertain("tuple", row, row_id, errors)
        for field in ("stakeholder", "opinion", "sentiment"):
            if not str(row.get(field) or "").strip():
                errors.append(item(f"tuple_{field}_nonempty", row_id, f"{field} is empty"))
        audit_evidence_cells("tuple", row, row_id, event_id, evidence_by_id, errors, warnings)


def audit_chain_rows(
    rows: list[dict[str, str]],
    event_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    seen_chain_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        row_id = row.get("chain_id") or f"row_{index}"
        event_id = str(row.get("event_id") or "")
        chain_id = str(row.get("chain_id") or "")
        if not event_id or event_id not in event_ids:
            errors.append(item("chain_event_id_exists", row_id, f"unknown event_id {event_id}"))
        if not chain_id:
            errors.append(item("chain_id_nonempty", row_id, "chain_id is empty"))
        elif chain_id in seen_chain_ids:
            errors.append(item("chain_id_unique", row_id, f"duplicate chain_id {chain_id}"))
        seen_chain_ids.add(chain_id)
        check_default_uncertain("chain", row, row_id, errors)
        if not str(row.get("event_chain") or "").strip():
            errors.append(item("chain_event_chain_nonempty", row_id, "event_chain is empty"))
        audit_evidence_cells("chain", row, row_id, event_id, evidence_by_id, errors, warnings)


def audit_evidence_cells(
    record_type: str,
    row: dict[str, str],
    row_id: str,
    event_id: str,
    evidence_by_id: dict[str, dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    ids = parse_ids(row.get("evidence_ids"))
    if not ids:
        errors.append(item(f"{record_type}_evidence_ids_nonempty", row_id, "evidence_ids is empty"))
    if not str(row.get("evidence_texts") or "").strip():
        errors.append(item(f"{record_type}_evidence_texts_nonempty", row_id, "evidence_texts is empty"))
    for evidence_id in ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            errors.append(item(f"{record_type}_evidence_id_exists", row_id, f"unknown evidence_id {evidence_id}"))
        elif str(evidence.get("event_id")) != str(event_id):
            errors.append(item(f"{record_type}_evidence_same_event", row_id, f"{evidence_id} belongs to {evidence.get('event_id')}"))
    text_blocks = [block.strip() for block in str(row.get("evidence_texts") or "").split("|||") if block.strip()]
    if text_blocks and ids and len(text_blocks) != len(ids):
        warnings.append(item(f"{record_type}_evidence_text_count_mismatch", row_id, f"{len(text_blocks)} text blocks for {len(ids)} evidence_ids"))


def check_default_uncertain(record_type: str, row: dict[str, str], row_id: str, errors: list[dict[str, Any]]) -> None:
    decision = str(row.get("review_decision") or "").strip()
    if decision not in VALID_REVIEW_DECISIONS:
        errors.append(item(f"{record_type}_review_decision_valid", row_id, f"invalid review_decision {decision}"))
    if decision != "uncertain":
        errors.append(item(f"{record_type}_review_decision_default_uncertain", row_id, f"review_decision is {decision}"))


def check_required_fields(record_type: str, fields: list[str], required: list[str], errors: list[dict[str, Any]]) -> None:
    missing = [field for field in required if field not in fields]
    for field in missing:
        errors.append(item(f"{record_type}_required_field_present", field, f"missing field {field}"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_csv_with_fields(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_json(path: Path, value: dict[str, Any]) -> None:
    backup_existing(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    backup_existing(path)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def backup_existing(path: Path) -> None:
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_{timestamp}"))


def parse_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).replace("|", ";").replace(",", ";").split(";") if item.strip()]


def item(check: str, row: str, message: str) -> dict[str, str]:
    return {"check": check, "row": row, "message": message}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Adjudication Sheet Pre-Review Audit",
        "",
        f"- ready_for_human_review: {report['ready_for_human_review']}",
        f"- total_errors: {report['total_errors']}",
        f"- total_warnings: {report['total_warnings']}",
        f"- counts: {report['counts']}",
        f"- error_counts: {report['error_counts']}",
        f"- warning_counts: {report['warning_counts']}",
        "",
        "## Errors",
    ]
    if report["errors"]:
        lines.extend(f"- {row['check']} / {row['row']}: {row['message']}" for row in report["errors"][:200])
    else:
        lines.append("- No blocking errors.")
    lines.append("")
    lines.append("## Warnings")
    if report["warnings"]:
        lines.extend(f"- {row['check']} / {row['row']}: {row['message']}" for row in report["warnings"][:200])
    else:
        lines.append("- No warnings.")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
