"""Prepare the PubEvent-SOA semi-real dataset from raw public snippets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from episoa.preprocess.privacy_filter import PrivacyFilterStats, clean_raw_evidence
from episoa.schemas.evidence import EvidenceRecord


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_dataset(
    *,
    input_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    """Clean raw evidence and write normalized EvidenceRecord JSONL."""
    stats = PrivacyFilterStats()
    cleaned_rows: list[dict[str, Any]] = []
    for raw in load_jsonl(input_path):
        try:
            cleaned = clean_raw_evidence(raw, stats)
            record = EvidenceRecord.model_validate(cleaned)
            cleaned_rows.append(record.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - report bad rows without stopping the whole batch.
            stats.skipped_records += 1
            stats.errors.append(f"{raw.get('evidence_id', '<missing>')}: {exc}")

    write_jsonl(cleaned_rows, output_path)
    report = stats.to_dict()
    report["input_path"] = str(Path(input_path))
    report["output_path"] = str(Path(output_path))
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare semi-real EpiSOA evidence data.")
    parser.add_argument("--input", default="data/pubevent_soa_semireal/evidence_raw.jsonl")
    parser.add_argument("--output", default="data/pubevent_soa_semireal/evidence_clean.jsonl")
    parser.add_argument("--report", default="data/pubevent_soa_semireal/cleaning_report.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = prepare_dataset(input_path=args.input, output_path=args.output, report_path=args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
