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


def normalize_support_label(value: str, verified: bool) -> str:
    label = value.strip().lower()
    if not label:
        return "supported" if verified else "unsupported"
    if label not in {"supported", "partially_supported", "unsupported"}:
        raise ValueError(f"support_label must be supported/partially_supported/unsupported, got {value!r}")
    return label


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
    verified = parse_bool(row.get("verified", ""))
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
        "support_label": normalize_support_label(row.get("support_label", ""), verified),
        "verified": verified,
        "notes": row.get("notes", "").strip(),
    }


def row_to_evidence(row: dict[str, str], index: int) -> dict[str, Any]:
    """Convert a human-reviewed annotation row into an evidence corpus record."""
    evidence_id = row.get("evidence_id", "").strip() or f"ev-{index:05d}"
    return {
        "evidence_id": evidence_id,
        "event_id": row.get("event_id", "").strip(),
        "platform": row.get("platform", "").strip() or "public_web",
        "url": row.get("url", "").strip(),
        "timestamp": row.get("timestamp", "").strip(),
        "source_type": row.get("source_type", "").strip() or "other",
        "text": row.get("text", "").strip(),
        "author_alias": "",
        "metadata": {
            "stakeholder": row.get("annotated_stakeholder", "").strip(),
            "opinion": row.get("annotated_opinion", "").strip(),
            "sentiment": row.get("annotated_sentiment", "").strip(),
            "rationale": row.get("annotated_rationale", "").strip(),
            "support_label": row.get("support_label", "").strip(),
            "human_reviewed": True,
        },
    }


def convert_csv_to_gold(
    input_path: str | Path,
    output_path: str | Path,
    adjudication_path: str | Path | None = None,
    evidence_output_path: str | Path | None = None,
) -> int:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("annotated_stakeholder") and not row.get("annotated_opinion"):
                continue
            rows.append(row_to_gold_tuple(row, len(rows) + 1))
            evidence_rows.append(row_to_evidence(row, len(evidence_rows) + 1))
    if adjudication_path:
        rows = _apply_adjudication(rows, adjudication_path)

    with output_path.open("w", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    if evidence_output_path:
        evidence_output = Path(evidence_output_path)
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        with evidence_output.open("w", encoding="utf-8") as handle:
            for record in evidence_rows:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(rows)


def _apply_adjudication(rows: list[dict[str, Any]], adjudication_path: str | Path) -> list[dict[str, Any]]:
    """Apply final adjudicated replacements by tuple_id."""
    path = Path(adjudication_path)
    if not path.exists():
        return rows
    replacements: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("tuple_id"):
                replacements[str(record["tuple_id"])] = record
    return [replacements.get(str(row.get("tuple_id")), row) for row in rows]


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
    parser.add_argument("--adjudication")
    parser.add_argument("--evidence-output")
    parser.add_argument("--validation-output", default="outputs/dataset_validation_formal.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    output_path = Path(args.output)
    row_count = convert_csv_to_gold(
        args.input,
        output_path,
        adjudication_path=args.adjudication,
        evidence_output_path=args.evidence_output,
    )
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
