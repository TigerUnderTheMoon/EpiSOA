#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build human adjudication CSV sheets from silver_v1 records."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SILVER_DIR = Path("data/pubevent_soa_lite/silver_v1")
DEFAULT_OUTPUT_DIR = Path("data/pubevent_soa_lite/human_gold_v1")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
PRIORITY_FIELDS = [
    "adjudication_priority_score",
    "priority_bucket",
    "priority_reason",
]

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
    *PRIORITY_FIELDS,
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
    *PRIORITY_FIELDS,
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
    tuple_rows = sort_priority_rows(tuple_rows, id_field="tuple_id")
    chain_rows = sort_priority_rows(chain_rows, id_field="chain_id")

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
        "priority_bucket_distribution": {
            "tuples": dict(Counter(row["priority_bucket"] for row in tuple_rows)),
            "chains": dict(Counter(row["priority_bucket"] for row in chain_rows)),
        },
        "top_priority_examples": {
            "tuples": top_priority_examples(tuple_rows, id_field="tuple_id"),
            "chains": top_priority_examples(chain_rows, id_field="chain_id"),
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
    priority = tuple_priority(row, ids, evidence_pack, chains_by_event.get(event_id, []))
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
        **priority,
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
    chain_nodes = parse_chain(row)
    priority = chain_priority(chain_nodes, ids, evidence_pack)
    return {
        "event_id": row.get("event_id", ""),
        "chain_id": row.get("chain_id") or row.get("candidate_chain_id") or row.get("gold_chain_id") or "",
        "event_chain": join_blocks(chain_nodes),
        "evidence_ids": join_ids(ids),
        "evidence_texts": join_blocks([evidence_text(ev) for ev in evidence_pack]),
        "evidence_source_types": join_blocks([source_type(ev) for ev in evidence_pack]),
        "evidence_urls": join_blocks([str(ev.get("url") or "") for ev in evidence_pack]),
        "evidence_titles": join_blocks([str(ev.get("title") or "") for ev in evidence_pack]),
        "evidence_dates": join_blocks([str(ev.get("publish_time") or "") for ev in evidence_pack]),
        **priority,
        "review_decision": "uncertain",
        "revised_event_chain": "",
        "revised_evidence_ids": "",
        "reviewer_note": "",
        "reviewer_id": "",
        "adjudication_status": "",
    }


def tuple_priority(
    row: dict[str, Any],
    evidence_ids: list[str],
    evidence_pack: list[dict[str, Any]],
    same_event_chains: list[dict[str, Any]],
) -> dict[str, str]:
    reasons: list[str] = []
    score = 0.0
    support_label = str(row.get("support_label") or "supported").strip().lower()
    if support_label and support_label != "supported":
        score += 0.30
        reasons.append("weak_support_label")
    if len(evidence_ids) < 2:
        score += 0.20
        reasons.append("few_evidence")
    source_types = {source_type(ev) for ev in evidence_pack if source_type(ev)}
    if evidence_pack and len(source_types) <= 1:
        score += 0.12
        reasons.append("single_source_type")
    chain_evidence_ids = {
        evidence_id
        for chain in same_event_chains
        for evidence_id in parse_ids(chain.get("evidence_ids"))
    }
    if chain_evidence_ids and evidence_ids and not (set(evidence_ids) & chain_evidence_ids):
        score += 0.22
        reasons.append("no_chain_evidence_overlap")
    text_fields = [
        str(row.get("stakeholder") or "").strip(),
        str(row.get("opinion") or "").strip(),
        str(row.get("rationale") or "").strip(),
    ]
    if any(len(value) < 4 for value in text_fields):
        score += 0.16
        reasons.append("short_candidate_text")
    return priority_fields(score, reasons)


def chain_priority(chain_nodes: list[str], evidence_ids: list[str], evidence_pack: list[dict[str, Any]]) -> dict[str, str]:
    reasons: list[str] = []
    score = 0.0
    if len(chain_nodes) < 3:
        score += 0.25
        reasons.append("short_chain")
    if len(evidence_ids) < 2:
        score += 0.20
        reasons.append("few_evidence")
    source_types = {source_type(ev) for ev in evidence_pack if source_type(ev)}
    if evidence_pack and len(source_types) <= 1:
        score += 0.12
        reasons.append("single_source_type")
    chain_text = " ".join(chain_nodes + [evidence_text(ev, limit=120) for ev in evidence_pack])
    if not has_response_or_resolution_signal(chain_text):
        score += 0.18
        reasons.append("missing_response_or_resolution_signal")
    if sum(len(evidence_text(ev, limit=600)) for ev in evidence_pack) < 120:
        score += 0.15
        reasons.append("short_evidence_text")
    return priority_fields(score, reasons)


def priority_fields(score: float, reasons: list[str]) -> dict[str, str]:
    score = round(min(1.0, max(0.0, score)), 3)
    if score >= 0.50:
        bucket = "high"
    elif score >= 0.25:
        bucket = "medium"
    else:
        bucket = "low"
    return {
        "adjudication_priority_score": f"{score:.3f}",
        "priority_bucket": bucket,
        "priority_reason": ";".join(dict.fromkeys(reasons)) or "low_risk",
    }


def has_response_or_resolution_signal(text: str) -> bool:
    keywords = [
        "response",
        "resolution",
        "respond",
        "resolved",
        "回应",
        "通报",
        "说明",
        "答复",
        "整改",
        "解决",
        "处理",
        "协调",
        "落实",
    ]
    return any(keyword in text for keyword in keywords)


def sort_priority_rows(rows: list[dict[str, Any]], *, id_field: str) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -safe_float(row.get("adjudication_priority_score")),
            str(row.get("event_id") or ""),
            str(row.get(id_field) or ""),
        ),
    )


def top_priority_examples(rows: list[dict[str, Any]], *, id_field: str, limit: int = 5) -> list[dict[str, str]]:
    examples = []
    for row in rows[:limit]:
        examples.append(
            {
                "event_id": str(row.get("event_id") or ""),
                id_field: str(row.get(id_field) or ""),
                "adjudication_priority_score": str(row.get("adjudication_priority_score") or ""),
                "priority_bucket": str(row.get("priority_bucket") or ""),
                "priority_reason": str(row.get("priority_reason") or ""),
            }
        )
    return examples


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
