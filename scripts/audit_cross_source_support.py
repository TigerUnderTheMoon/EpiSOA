#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit whether tuple/chain claims are supported by independent sources."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_cross_source_support(
        tuples_path=Path(args.tuples),
        chains_path=Path(args.chains),
        evidence_path=Path(args.evidence),
        output_dir=Path(args.output_dir),
        min_independent_sources=int(args.min_independent_sources),
        annotated_output_dir=Path(args.annotated_output_dir) if args.annotated_output_dir else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["low_confidence_total"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit cross-source support for silver or human gold rows.")
    parser.add_argument("--tuples", default="data/pubevent_soa_lite/silver_v1/silver_tuples_v1.jsonl")
    parser.add_argument("--chains", default="data/pubevent_soa_lite/silver_v1/silver_event_chains_v1.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
    parser.add_argument("--output-dir", default="data/pubevent_soa_lite/human_gold_v1/audit")
    parser.add_argument("--min-independent-sources", type=int, default=2)
    parser.add_argument("--annotated-output-dir", default="", help="Optional directory for JSONL copies with confidence_route fields.")
    return parser


def audit_cross_source_support(
    *,
    tuples_path: Path,
    chains_path: Path,
    evidence_path: Path,
    output_dir: Path,
    min_independent_sources: int = 2,
    annotated_output_dir: Path | None = None,
) -> dict[str, Any]:
    tuples = read_jsonl(tuples_path)
    chains = read_jsonl(chains_path)
    evidence = read_jsonl(evidence_path)
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}

    tuple_audits = [
        audit_row("tuple", row, evidence_by_id, min_independent_sources)
        for row in tuples
    ]
    chain_audits = [
        audit_row("chain", row, evidence_by_id, min_independent_sources)
        for row in chains
    ]
    all_audits = tuple_audits + chain_audits
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "cross_source_support_audit.json", {
        "min_independent_sources": min_independent_sources,
        "counts": dict(Counter(item["confidence_route"] for item in all_audits)),
        "tuple_counts": dict(Counter(item["confidence_route"] for item in tuple_audits)),
        "chain_counts": dict(Counter(item["confidence_route"] for item in chain_audits)),
        "low_confidence_records": [item for item in all_audits if item["confidence_route"] == "low_confidence"],
    })
    write_csv(output_dir / "cross_source_support_audit.csv", all_audits)

    if annotated_output_dir is not None:
        annotated_output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(
            annotated_output_dir / tuples_path.name,
            [annotate_row(row, audit) for row, audit in zip(tuples, tuple_audits)],
        )
        write_jsonl(
            annotated_output_dir / chains_path.name,
            [annotate_row(row, audit) for row, audit in zip(chains, chain_audits)],
        )

    return {
        "status": "completed",
        "tuples": len(tuples),
        "chains": len(chains),
        "evidence": len(evidence),
        "min_independent_sources": min_independent_sources,
        "low_confidence_total": sum(1 for item in all_audits if item["confidence_route"] == "low_confidence"),
        "outputs": {
            "json": str(output_dir / "cross_source_support_audit.json"),
            "csv": str(output_dir / "cross_source_support_audit.csv"),
        },
    }


def audit_row(
    record_type: str,
    row: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
    min_independent_sources: int,
) -> dict[str, Any]:
    evidence_ids = parse_ids(row.get("evidence_ids"))
    signatures = []
    missing = []
    for evidence_id in evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            missing.append(evidence_id)
            continue
        signatures.append(source_signature(evidence))
    unique_signatures = sorted({item for item in signatures if item})
    low_confidence = len(unique_signatures) < min_independent_sources or bool(missing)
    record_id = (
        row.get("tuple_id")
        or row.get("candidate_id")
        or row.get("gold_tuple_id")
        or row.get("chain_id")
        or row.get("candidate_chain_id")
        or ""
    )
    return {
        "record_type": record_type,
        "event_id": str(row.get("event_id") or ""),
        "record_id": str(record_id),
        "evidence_ids": ";".join(evidence_ids),
        "independent_source_count": len(unique_signatures),
        "independent_sources": ";".join(unique_signatures),
        "missing_evidence_ids": ";".join(missing),
        "confidence_route": "low_confidence" if low_confidence else "silver_candidate",
        "required_action": "human_review_required" if low_confidence else "standard_review",
    }


def annotate_row(row: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["independent_source_count"] = audit["independent_source_count"]
    output["confidence_route"] = audit["confidence_route"]
    output["required_action"] = audit["required_action"]
    return output


def source_signature(row: dict[str, Any]) -> str:
    url = str(row.get("url") or "").strip()
    if url:
        host = urlsplit(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            return host
    return str(row.get("source_type") or row.get("source") or row.get("platform") or "unknown").strip().lower()


def parse_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").replace("|", ";").replace(",", ";").split(";") if part.strip()]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "record_type",
        "event_id",
        "record_id",
        "evidence_ids",
        "independent_source_count",
        "independent_sources",
        "missing_evidence_ids",
        "confidence_route",
        "required_action",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
