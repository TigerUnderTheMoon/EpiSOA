#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convert reviewed adjudication sheets into human_gold_v1 JSONL files."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("data/pubevent_soa_lite/human_gold_v1")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
VALID_DECISIONS = {"accept", "revise", "drop", "add_missing", "uncertain"}
VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}
VALID_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "insufficient_evidence", ""}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = convert_adjudication_to_human_gold(
        tuple_sheet=Path(args.tuple_sheet),
        chain_sheet=Path(args.chain_sheet),
        evidence_path=Path(args.evidence),
        events_path=Path(args.events),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert human adjudication CSVs to human_gold_v1.")
    parser.add_argument("--tuple-sheet", default=str(DEFAULT_OUTPUT_DIR / "human_tuple_adjudication_sheet.csv"))
    parser.add_argument("--chain-sheet", default=str(DEFAULT_OUTPUT_DIR / "human_chain_adjudication_sheet.csv"))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def convert_adjudication_to_human_gold(
    *,
    tuple_sheet: Path,
    chain_sheet: Path,
    evidence_path: Path,
    events_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    tuple_rows = read_csv(tuple_sheet)
    chain_rows = read_csv(chain_sheet)
    evidence = read_jsonl(evidence_path)
    events = read_jsonl(events_path)
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}
    event_ids = {str(row.get("event_id")) for row in events if row.get("event_id")}

    gold_tuples, tuple_log = convert_tuple_rows(tuple_rows, evidence_by_id, event_ids)
    gold_chains, chain_log = convert_chain_rows(chain_rows, evidence_by_id, event_ids)
    validate_unique_ids(gold_tuples, id_field="tuple_id", object_name="tuple")
    validate_unique_ids(gold_chains, id_field="chain_id", object_name="chain")

    output_dir.mkdir(parents=True, exist_ok=True)
    tuples_out = output_dir / "human_gold_tuples_v1.jsonl"
    chains_out = output_dir / "human_gold_event_chains_v1.jsonl"
    manifest_out = output_dir / "human_gold_manifest_v1.json"
    rejected_out = output_dir / "rejected_or_uncertain_log.csv"
    write_jsonl(tuples_out, gold_tuples)
    write_jsonl(chains_out, gold_chains)
    write_csv(rejected_out, tuple_log + chain_log, [
        "record_type", "event_id", "record_id", "review_decision", "reason", "reviewer_id", "reviewer_note",
    ])

    tuple_decisions = Counter(normalize_decision(row.get("review_decision")) for row in tuple_rows)
    chain_decisions = Counter(normalize_decision(row.get("review_decision")) for row in chain_rows)
    manifest = {
        "dataset_name": "pubevent_soa_lite_human_gold_v1",
        "dataset_level": "human_gold",
        "source": "human_adjudication",
        "human_verified": True,
        "ready_for_main_experiment": False,
        "original_files_modified": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "tuple_sheet": str(tuple_sheet),
            "chain_sheet": str(chain_sheet),
            "canonical_evidence": str(evidence_path),
            "events": str(events_path),
        },
        "outputs": {
            "human_gold_tuples": str(tuples_out),
            "human_gold_event_chains": str(chains_out),
            "human_gold_manifest": str(manifest_out),
            "rejected_or_uncertain_log": str(rejected_out),
        },
        "counts": {
            "human_gold_tuples": len(gold_tuples),
            "human_gold_event_chains": len(gold_chains),
            "rejected_or_uncertain_rows": len(tuple_log) + len(chain_log),
        },
        "decision_counts": {
            "tuples": dict(tuple_decisions),
            "chains": dict(chain_decisions),
        },
        "notes": [
            "ready_for_main_experiment is set by scripts/audit_human_gold.py and remains false until total_issues=0.",
            "uncertain and drop rows are excluded from human_gold outputs.",
        ],
    }
    write_json(manifest_out, manifest)
    return manifest


def convert_tuple_rows(
    rows: list[dict[str, str]],
    evidence_by_id: dict[str, dict[str, Any]],
    event_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    output: list[dict[str, Any]] = []
    log: list[dict[str, str]] = []
    event_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        decision = normalize_decision(row.get("review_decision"))
        record_id = row.get("tuple_id", "")
        event_id = row.get("event_id", "")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid review_decision for tuple {record_id}: {decision}")
        if decision in {"drop", "uncertain"}:
            log.append(log_row("tuple", event_id, record_id, decision, f"excluded_by_{decision}", row))
            continue
        if decision == "accept":
            candidate = {
                "tuple_id": record_id,
                "event_id": event_id,
                "stakeholder": row.get("stakeholder", ""),
                "opinion": row.get("opinion", ""),
                "sentiment": row.get("sentiment", ""),
                "rationale": row.get("rationale", ""),
                "evidence_ids": parse_ids(row.get("evidence_ids")),
                "support_label": row.get("support_label", "supported") or "supported",
                "source_silver_tuple_id": record_id,
                "review_decision": decision,
            }
        elif decision == "revise":
            candidate = {
                "tuple_id": record_id,
                "event_id": event_id,
                "stakeholder": row.get("revised_stakeholder", ""),
                "opinion": row.get("revised_opinion", ""),
                "sentiment": row.get("revised_sentiment", ""),
                "rationale": row.get("revised_rationale", ""),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids")),
                "support_label": row.get("support_label", "supported") or "supported",
                "source_silver_tuple_id": record_id,
                "review_decision": decision,
            }
        else:
            event_counts[event_id] += 1
            new_id = record_id or f"HG_{event_id}_{event_counts[event_id]:03d}"
            candidate = {
                "tuple_id": new_id,
                "event_id": event_id,
                "stakeholder": row.get("revised_stakeholder") or row.get("stakeholder", ""),
                "opinion": row.get("revised_opinion") or row.get("opinion", ""),
                "sentiment": row.get("revised_sentiment") or row.get("sentiment", ""),
                "rationale": row.get("revised_rationale") or row.get("rationale", ""),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids") or row.get("evidence_ids")),
                "support_label": row.get("support_label", "supported") or "supported",
                "source_silver_tuple_id": record_id,
                "review_decision": decision,
            }
        validate_tuple(candidate, evidence_by_id, event_ids)
        candidate["annotation_provenance"] = provenance(row, decision)
        output.append(candidate)
    return output, log


def convert_chain_rows(
    rows: list[dict[str, str]],
    evidence_by_id: dict[str, dict[str, Any]],
    event_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    output: list[dict[str, Any]] = []
    log: list[dict[str, str]] = []
    event_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        decision = normalize_decision(row.get("review_decision"))
        chain_id = row.get("chain_id", "")
        event_id = row.get("event_id", "")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid review_decision for chain {chain_id}: {decision}")
        if decision in {"drop", "uncertain"}:
            log.append(log_row("chain", event_id, chain_id, decision, f"excluded_by_{decision}", row))
            continue
        if decision == "accept":
            candidate = {
                "chain_id": chain_id,
                "event_id": event_id,
                "event_chain": parse_chain(row.get("event_chain")),
                "evidence_ids": parse_ids(row.get("evidence_ids")),
                "source_silver_chain_id": chain_id,
                "review_decision": decision,
            }
        elif decision == "revise":
            candidate = {
                "chain_id": chain_id,
                "event_id": event_id,
                "event_chain": parse_chain(row.get("revised_event_chain")),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids")),
                "source_silver_chain_id": chain_id,
                "review_decision": decision,
            }
        else:
            event_counts[event_id] += 1
            new_id = chain_id or f"HGC_{event_id}_{event_counts[event_id]:03d}"
            candidate = {
                "chain_id": new_id,
                "event_id": event_id,
                "event_chain": parse_chain(row.get("revised_event_chain") or row.get("event_chain")),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids") or row.get("evidence_ids")),
                "source_silver_chain_id": chain_id,
                "review_decision": decision,
            }
        validate_chain(candidate, evidence_by_id, event_ids)
        candidate["annotation_provenance"] = provenance(row, decision)
        output.append(candidate)
    return output, log


def validate_tuple(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]], event_ids: set[str]) -> None:
    prefix = f"tuple {row.get('tuple_id')}"
    if row.get("event_id") not in event_ids:
        raise ValueError(f"{prefix}: unknown event_id {row.get('event_id')}")
    for field in ("tuple_id", "stakeholder", "opinion", "rationale"):
        if not str(row.get(field) or "").strip():
            raise ValueError(f"{prefix}: missing {field}")
    if row.get("sentiment") not in VALID_SENTIMENTS:
        raise ValueError(f"{prefix}: invalid sentiment {row.get('sentiment')}")
    if row.get("support_label") not in VALID_SUPPORT_LABELS:
        raise ValueError(f"{prefix}: invalid support_label {row.get('support_label')}")
    ids = row.get("evidence_ids") or []
    if not ids:
        raise ValueError(f"{prefix}: missing evidence_ids")
    validate_evidence_ids(prefix, row.get("event_id", ""), ids, evidence_by_id)


def validate_chain(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]], event_ids: set[str]) -> None:
    prefix = f"chain {row.get('chain_id')}"
    if row.get("event_id") not in event_ids:
        raise ValueError(f"{prefix}: unknown event_id {row.get('event_id')}")
    if not str(row.get("chain_id") or "").strip():
        raise ValueError(f"{prefix}: missing chain_id")
    if not row.get("event_chain"):
        raise ValueError(f"{prefix}: missing event_chain")
    ids = row.get("evidence_ids") or []
    if not ids:
        raise ValueError(f"{prefix}: missing evidence_ids")
    validate_evidence_ids(prefix, row.get("event_id", ""), ids, evidence_by_id)


def validate_evidence_ids(prefix: str, event_id: str, ids: list[str], evidence_by_id: dict[str, dict[str, Any]]) -> None:
    for evidence_id in ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise ValueError(f"{prefix}: unknown evidence_id {evidence_id}")
        if str(evidence.get("event_id")) != str(event_id):
            raise ValueError(f"{prefix}: evidence_id {evidence_id} belongs to event {evidence.get('event_id')}")


def validate_unique_ids(rows: list[dict[str, Any]], *, id_field: str, object_name: str) -> None:
    seen: set[str] = set()
    for row in rows:
        value = str(row.get(id_field) or "")
        if value in seen:
            raise ValueError(f"duplicate {object_name} {id_field}: {value}")
        seen.add(value)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    backup_existing(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    backup_existing(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    backup_existing(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def backup_existing(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.bak_{timestamp}"))


def normalize_decision(value: Any) -> str:
    return str(value or "").strip()


def parse_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).replace("|", ";").replace(",", ";").split(";") if item.strip()]


def parse_chain(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if not value:
        return []
    text = str(value)
    if "|||" in text:
        parts = text.split("|||")
    elif "->" in text:
        parts = text.split("->")
    else:
        parts = text.split(";")
    return [part.strip() for part in parts if part.strip()]


def provenance(row: dict[str, str], decision: str) -> dict[str, str]:
    return {
        "source": "human_adjudication",
        "review_decision": decision,
        "reviewer_id": row.get("reviewer_id", ""),
        "adjudication_status": row.get("adjudication_status", ""),
        "reviewer_note": row.get("reviewer_note", ""),
    }


def log_row(record_type: str, event_id: str, record_id: str, decision: str, reason: str, row: dict[str, str]) -> dict[str, str]:
    return {
        "record_type": record_type,
        "event_id": event_id,
        "record_id": record_id,
        "review_decision": decision,
        "reason": reason,
        "reviewer_id": row.get("reviewer_id", ""),
        "reviewer_note": row.get("reviewer_note", ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
