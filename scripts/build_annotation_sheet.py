"""Build a CSV annotation sheet from EpiSOA event and evidence JSONL files."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "event_id",
    "evidence_id",
    "platform",
    "url",
    "timestamp",
    "source_type",
    "text",
    "suggested_stakeholder",
    "suggested_sentiment",
    "annotated_stakeholder",
    "annotated_opinion",
    "annotated_sentiment",
    "annotated_rationale",
    "annotated_event_chain",
    "annotated_evidence_ids",
    "support_score",
    "verified",
    "notes",
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            records.append(json.loads(line))
    return records


def build_rows(events_path: str | Path, evidence_path: str | Path) -> list[dict[str, Any]]:
    events = {record.get("event_id"): record for record in load_jsonl(Path(events_path))}
    rows: list[dict[str, Any]] = []
    for record in load_jsonl(Path(evidence_path)):
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        event = events.get(record.get("event_id"), {})
        event_chain = event.get("event_chain") if isinstance(event.get("event_chain"), list) else []
        rows.append(
            {
                "event_id": record.get("event_id", ""),
                "evidence_id": record.get("evidence_id", ""),
                "platform": record.get("platform", ""),
                "url": record.get("url", ""),
                "timestamp": record.get("timestamp", ""),
                "source_type": record.get("source_type", ""),
                "text": record.get("text", ""),
                "suggested_stakeholder": metadata.get("stakeholder", ""),
                "suggested_sentiment": metadata.get("sentiment", ""),
                "annotated_stakeholder": "",
                "annotated_opinion": "",
                "annotated_sentiment": "",
                "annotated_rationale": "",
                "annotated_event_chain": ";".join(str(item) for item in event_chain),
                "annotated_evidence_ids": record.get("evidence_id", ""),
                "support_score": "",
                "verified": "",
                "notes": "",
            }
        )
    return rows


def write_annotation_sheet(events_path: str | Path, evidence_path: str | Path, output_path: str | Path) -> int:
    rows = build_rows(events_path, evidence_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an EpiSOA annotation CSV sheet.")
    parser.add_argument("--events", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    row_count = write_annotation_sheet(args.events, args.evidence, args.output)
    print(f"wrote annotation sheet with {row_count} rows: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
