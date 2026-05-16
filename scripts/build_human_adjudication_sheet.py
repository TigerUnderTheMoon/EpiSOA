#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build human adjudication CSV sheets from silver_v1 records."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SILVER_DIR = Path("data/pubevent_soa_lite/silver_v1")
DEFAULT_OUTPUT_DIR = Path("data/pubevent_soa_lite/human_gold_v1")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")

TUPLE_FIELDS = [
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
    "evidence_urls",
    "evidence_titles",
    "evidence_dates",
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

CHAIN_FIELDS = [
    "event_id",
    "chain_id",
    "event_chain",
    "evidence_ids",
    "evidence_texts",
    "evidence_source_types",
    "evidence_urls",
    "evidence_titles",
    "evidence_dates",
    "review_decision",
    "revised_event_chain",
    "revised_evidence_ids",
    "reviewer_note",
    "reviewer_id",
    "adjudication_status",
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_human_adjudication_sheet(
        silver_tuples_path=Path(args.silver_tuples),
        silver_chains_path=Path(args.silver_chains),
        evidence_path=Path(args.evidence),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build human adjudication sheets from silver_v1.")
    parser.add_argument("--silver-tuples", default=str(DEFAULT_SILVER_DIR / "silver_tuples_v1.jsonl"))
    parser.add_argument("--silver-chains", default=str(DEFAULT_SILVER_DIR / "silver_event_chains_v1.jsonl"))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def build_human_adjudication_sheet(
    *,
    silver_tuples_path: Path,
    silver_chains_path: Path,
    evidence_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    tuples = read_jsonl(silver_tuples_path)
    chains = read_jsonl(silver_chains_path)
    evidence = read_jsonl(evidence_path)
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}
    chains_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in chains:
        chains_by_event[str(row.get("event_id") or "")].append(row)

    tuple_rows = [tuple_sheet_row(row, chains_by_event, evidence_by_id) for row in tuples]
    chain_rows = [chain_sheet_row(row, evidence_by_id) for row in chains]

    output_dir.mkdir(parents=True, exist_ok=True)
    tuple_sheet = output_dir / "human_tuple_adjudication_sheet.csv"
    chain_sheet = output_dir / "human_chain_adjudication_sheet.csv"
    write_csv(tuple_sheet, tuple_rows, TUPLE_FIELDS)
    write_csv(chain_sheet, chain_rows, CHAIN_FIELDS)

    return {
        "status": "completed",
        "silver_tuples": str(silver_tuples_path),
        "silver_event_chains": str(silver_chains_path),
        "canonical_evidence": str(evidence_path),
        "outputs": {
            "human_tuple_adjudication_sheet": str(tuple_sheet),
            "human_chain_adjudication_sheet": str(chain_sheet),
        },
        "counts": {
            "tuple_rows": len(tuple_rows),
            "chain_rows": len(chain_rows),
            "evidence_records": len(evidence),
        },
        "review_decision_allowed_values": ["accept", "revise", "drop", "add_missing", "uncertain"],
        "default_review_decision": "uncertain",
    }


def tuple_sheet_row(
    row: dict[str, Any],
    chains_by_event: dict[str, list[dict[str, Any]]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    event_id = str(row.get("event_id") or "")
    ids = parse_ids(row.get("evidence_ids"))
    evidence_pack = [evidence_by_id.get(eid, {}) for eid in ids]
    return {
        "event_id": event_id,
        "tuple_id": row.get("candidate_id") or row.get("tuple_id") or row.get("gold_tuple_id") or "",
        "stakeholder": row.get("stakeholder", ""),
        "opinion": row.get("opinion", ""),
        "sentiment": row.get("sentiment", ""),
        "rationale": row.get("rationale", ""),
        "event_chain": join_blocks(chain_summary(chains_by_event.get(event_id, []))),
        "evidence_ids": join_ids(ids),
        "evidence_texts": join_blocks([evidence_text(ev) for ev in evidence_pack]),
        "evidence_source_types": join_blocks([source_type(ev) for ev in evidence_pack]),
        "evidence_urls": join_blocks([str(ev.get("url") or "") for ev in evidence_pack]),
        "evidence_titles": join_blocks([str(ev.get("title") or "") for ev in evidence_pack]),
        "evidence_dates": join_blocks([str(ev.get("publish_time") or "") for ev in evidence_pack]),
        "review_decision": "uncertain",
        "revised_stakeholder": "",
        "revised_opinion": "",
        "revised_sentiment": "",
        "revised_rationale": "",
        "revised_evidence_ids": "",
        "reviewer_note": "",
        "reviewer_id": "",
        "adjudication_status": "",
    }


def chain_sheet_row(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = parse_ids(row.get("evidence_ids"))
    evidence_pack = [evidence_by_id.get(eid, {}) for eid in ids]
    return {
        "event_id": row.get("event_id", ""),
        "chain_id": row.get("chain_id") or row.get("candidate_chain_id") or row.get("gold_chain_id") or "",
        "event_chain": join_blocks(parse_chain(row)),
        "evidence_ids": join_ids(ids),
        "evidence_texts": join_blocks([evidence_text(ev) for ev in evidence_pack]),
        "evidence_source_types": join_blocks([source_type(ev) for ev in evidence_pack]),
        "evidence_urls": join_blocks([str(ev.get("url") or "") for ev in evidence_pack]),
        "evidence_titles": join_blocks([str(ev.get("title") or "") for ev in evidence_pack]),
        "evidence_dates": join_blocks([str(ev.get("publish_time") or "") for ev in evidence_pack]),
        "review_decision": "uncertain",
        "revised_event_chain": "",
        "revised_evidence_ids": "",
        "reviewer_note": "",
        "reviewer_id": "",
        "adjudication_status": "",
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
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


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
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


def parse_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).replace("|", ";").replace(",", ";").split(";") if item.strip()]


def parse_chain(row: dict[str, Any]) -> list[str]:
    value = row.get("event_chain") or row.get("chain_nodes") or []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value:
        return [part.strip() for part in str(value).split(";") if part.strip()]
    return []


def chain_summary(rows: list[dict[str, Any]]) -> list[str]:
    summaries = []
    for row in rows:
        chain_id = row.get("chain_id") or row.get("candidate_chain_id") or ""
        chain = " -> ".join(parse_chain(row))
        summaries.append(f"{chain_id}: {chain}".strip(": "))
    return summaries


def evidence_text(row: dict[str, Any], limit: int = 600) -> str:
    text = " ".join(str(row.get("text") or "").split())
    return text[:limit]


def source_type(row: dict[str, Any]) -> str:
    return str(row.get("source_type") or row.get("source") or "")


def join_ids(values: list[str]) -> str:
    return ";".join(values)


def join_blocks(values: list[str]) -> str:
    return " ||| ".join(str(item) for item in values if str(item).strip())


if __name__ == "__main__":
    raise SystemExit(main())
