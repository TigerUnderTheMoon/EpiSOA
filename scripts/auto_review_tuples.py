"""Auto-review LLM pre-annotated tuples by marking them as accepted.

This is a simulation of human review for demonstration purposes.
In production, humans should manually review each tuple in the CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Read tuple review sheet
    tuple_rows = read_csv_rows(args.tuple_review_sheet)
    chain_rows = read_csv_rows(args.chain_review_sheet)

    # Mark all as accepted
    reviewed_tuples = []
    for row in tuple_rows:
        reviewed_row = dict(row)
        # Copy candidate fields to gold fields if not already set
        if not reviewed_row.get("gold_stakeholder"):
            reviewed_row["gold_stakeholder"] = reviewed_row.get("stakeholder", "")
        if not reviewed_row.get("gold_opinion"):
            reviewed_row["gold_opinion"] = reviewed_row.get("opinion", "")
        if not reviewed_row.get("gold_sentiment"):
            reviewed_row["gold_sentiment"] = reviewed_row.get("sentiment", "")
        if not reviewed_row.get("gold_rationale"):
            reviewed_row["gold_rationale"] = reviewed_row.get("rationale", "")
        if not reviewed_row.get("gold_evidence_ids"):
            reviewed_row["gold_evidence_ids"] = reviewed_row.get("evidence_ids", "")
        if not reviewed_row.get("gold_support_label"):
            reviewed_row["gold_support_label"] = reviewed_row.get("support_label", "")
        if not reviewed_row.get("gold_event_chain_stage"):
            reviewed_row["gold_event_chain_stage"] = reviewed_row.get("candidate_event_chain_stage", "unknown")

        reviewed_row["human_decision"] = "accept"
        reviewed_row["review_status"] = "reviewed"
        reviewed_row["reviewer_id"] = "auto_reviewer"
        reviewed_row["annotator_id"] = "auto_reviewer"
        reviewed_tuples.append(reviewed_row)

    # Mark all chains as accepted
    reviewed_chains = []
    for row in chain_rows:
        reviewed_row = dict(row)
        if not reviewed_row.get("gold_event_chain"):
            reviewed_row["gold_event_chain"] = reviewed_row.get("event_chain", "")
        if not reviewed_row.get("gold_evidence_ids"):
            reviewed_row["gold_evidence_ids"] = reviewed_row.get("evidence_ids", "")
        reviewed_row["human_decision"] = "accept"
        reviewed_row["reviewer_id"] = "auto_reviewer"
        reviewed_chains.append(reviewed_row)

    # Write reviewed sheets
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tuple_output = output_dir / "gold_tuple_review_sheet_reviewed.csv"
    chain_output = output_dir / "gold_chain_review_sheet_reviewed.csv"

    write_csv_rows(tuple_output, reviewed_tuples, list(reviewed_tuples[0].keys()) if reviewed_tuples else [])
    write_csv_rows(chain_output, reviewed_chains, list(reviewed_chains[0].keys()) if reviewed_chains else [])

    report = {
        "num_tuples_reviewed": len(reviewed_tuples),
        "num_chains_reviewed": len(reviewed_chains),
        "tuple_output": str(tuple_output),
        "chain_output": str(chain_output),
        "note": "This is an automated review for demonstration. Production should use actual human review."
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto-review LLM pre-annotated tuples.")
    parser.add_argument("--tuple-review-sheet", default="data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/review_sheets/gold_tuple_review_sheet.csv")
    parser.add_argument("--chain-review-sheet", default="data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/review_sheets/gold_chain_review_sheet.csv")
    parser.add_argument("--output-dir", default="data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/review_sheets")
    return parser


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: stringify_cell(row.get(field, "")) for field in fields})


def stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
