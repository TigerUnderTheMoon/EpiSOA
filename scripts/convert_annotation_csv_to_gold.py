"""Convert a filled EpiSOA annotation CSV into gold tuple JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_dataset import validate_dataset


def split_semicolon(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"verified must be bool-like, got {value!r}")


def parse_support_score(value: str) -> float:
    score = float(value)
    if not 0 <= score <= 1:
        raise ValueError(f"support_score must be between 0 and 1, got {value!r}")
    return score


def row_to_gold_tuple(row: dict[str, str], index: int) -> dict[str, Any]:
    event_chain = split_semicolon(row.get("annotated_event_chain", ""))
    evidence_ids = split_semicolon(row.get("annotated_evidence_ids", ""))
    event_id = row.get("event_id", "").strip()
    evidence = [
        {
            "evidence_id": evidence_id,
        }
        for evidence_id in evidence_ids
    ]
    return {
        "tuple_id": f"tuple-{index:05d}",
        "event_id": event_id,
        "stakeholder": row.get("annotated_stakeholder", "").strip(),
        "opinion": row.get("annotated_opinion", "").strip(),
        "sentiment": row.get("annotated_sentiment", "").strip(),
        "rationale": row.get("annotated_rationale", "").strip(),
        "event_chain": event_chain,
        "evidence_ids": evidence_ids,
        "evidence": evidence,
        "support_score": parse_support_score(row.get("support_score", "").strip()),
        "verified": parse_bool(row.get("verified", "")),
        "notes": row.get("notes", "").strip(),
    }


def convert_csv_to_gold(input_path: str | Path, output_path: str | Path) -> int:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("annotated_stakeholder") and not row.get("annotated_opinion"):
                continue
            rows.append(row_to_gold_tuple(row, len(rows) + 1))

    with output_path.open("w", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(rows)


def default_validation_paths(output_path: Path) -> tuple[Path, Path, Path, Path]:
    dataset_dir = output_path.parent
    return (
        dataset_dir / "events.jsonl",
        dataset_dir / "evidence.jsonl",
        output_path,
        dataset_dir / "gold_event_chains.jsonl",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert filled EpiSOA annotation CSV to gold tuples.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--validation-output", default="outputs/dataset_validation_formal.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    output_path = Path(args.output)
    row_count = convert_csv_to_gold(args.input, output_path)
    events_path, evidence_path, gold_tuples_path, gold_event_chains_path = default_validation_paths(output_path)
    report = validate_dataset(events_path, evidence_path, gold_tuples_path, gold_event_chains_path)
    validation_output = Path(args.validation_output)
    validation_output.parent.mkdir(parents=True, exist_ok=True)
    validation_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {row_count} gold tuples: {output_path}")
    print(f"wrote dataset validation report: {validation_output}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
