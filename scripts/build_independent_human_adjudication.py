#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build and audit independent human adjudication sheets."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ANNOTATORS = ("annotator_A", "annotator_B", "annotator_C")
DECISION_LABELS = ("accept", "revise", "drop", "add_missing", "uncertain")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    if args.command == "prepare":
        report = prepare_independent_sheets(
            tuple_sheet=Path(args.tuple_sheet),
            chain_sheet=Path(args.chain_sheet),
            output_dir=output_dir,
            annotators=tuple(split_csv(args.annotators)),
        )
    else:
        report = audit_independent_annotations(
            tuple_sheets=[Path(item) for item in split_csv(args.tuple_sheets)],
            chain_sheets=[Path(item) for item in split_csv(args.chain_sheets)],
            output_dir=output_dir,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report.get("status") == "blocked" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Three-annotator human gold workflow.")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Create independent blank sheets for each annotator.")
    prepare.add_argument("--tuple-sheet", default="data/pubevent_soa_lite/human_gold_v1/human_tuple_adjudication_sheet.csv")
    prepare.add_argument("--chain-sheet", default="data/pubevent_soa_lite/human_gold_v1/human_chain_adjudication_sheet.csv")
    prepare.add_argument("--output-dir", default="data/pubevent_soa_lite/human_gold_v1/independent")
    prepare.add_argument("--annotators", default=",".join(ANNOTATORS))

    audit = sub.add_parser("audit", help="Compute IAA and write conflict sheets.")
    audit.add_argument("--tuple-sheets", required=True, help="Comma-separated completed tuple CSVs.")
    audit.add_argument("--chain-sheets", required=True, help="Comma-separated completed chain CSVs.")
    audit.add_argument("--output-dir", default="data/pubevent_soa_lite/human_gold_v1/independent_audit")
    return parser


def prepare_independent_sheets(
    *,
    tuple_sheet: Path,
    chain_sheet: Path,
    output_dir: Path,
    annotators: tuple[str, ...],
) -> dict[str, Any]:
    tuple_rows = read_csv(tuple_sheet)
    chain_rows = read_csv(chain_sheet)
    outputs: dict[str, dict[str, str]] = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    for annotator in annotators:
        annotator_dir = output_dir / annotator
        annotator_dir.mkdir(parents=True, exist_ok=True)
        tuple_out = annotator_dir / "human_tuple_adjudication_sheet.csv"
        chain_out = annotator_dir / "human_chain_adjudication_sheet.csv"
        write_csv(tuple_out, reset_for_annotator(tuple_rows, annotator))
        write_csv(chain_out, reset_for_annotator(chain_rows, annotator))
        outputs[annotator] = {"tuple_sheet": str(tuple_out), "chain_sheet": str(chain_out)}
    return {
        "status": "completed",
        "annotators": list(annotators),
        "tuple_rows": len(tuple_rows),
        "chain_rows": len(chain_rows),
        "outputs": outputs,
        "qualification_required": {"test_items": 20, "minimum_accuracy": 0.85},
    }


def audit_independent_annotations(
    *,
    tuple_sheets: list[Path],
    chain_sheets: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    if len(tuple_sheets) < 2 or len(chain_sheets) < 2:
        return {"status": "blocked", "reason": "at least two independent annotator sheets are required"}
    output_dir.mkdir(parents=True, exist_ok=True)
    tuple_votes = collect_votes(tuple_sheets, "tuple")
    chain_votes = collect_votes(chain_sheets, "chain")
    tuple_report = agreement_report(tuple_votes)
    chain_report = agreement_report(chain_votes)
    conflicts = conflict_rows(tuple_votes) + conflict_rows(chain_votes)
    write_csv(output_dir / "adjudication_conflict_sheet.csv", conflicts)
    report = {
        "status": "completed",
        "tuple_iaa": tuple_report,
        "chain_iaa": chain_report,
        "conflict_count": len(conflicts),
        "routing": {
            "kappa_gt_0_8": "auto_pass_after_schema_audit",
            "kappa_0_6_to_0_8": "expert_fast_review",
            "kappa_lt_0_6": "relabel_or_guideline_revision",
        },
        "outputs": {"conflict_sheet": str(output_dir / "adjudication_conflict_sheet.csv")},
    }
    (output_dir / "independent_annotation_iaa_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "independent_annotation_iaa_report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def reset_for_annotator(rows: list[dict[str, str]], annotator: str) -> list[dict[str, str]]:
    output = []
    for row in rows:
        item = dict(row)
        item["review_decision"] = "uncertain"
        item["reviewer_id"] = annotator
        item["annotator_id"] = annotator
        item["adjudication_status"] = "independent_review"
        output.append(item)
    return output


def collect_votes(paths: list[Path], record_type: str) -> dict[str, dict[str, Any]]:
    votes: dict[str, dict[str, Any]] = {}
    id_field = "tuple_id" if record_type == "tuple" else "chain_id"
    for index, path in enumerate(paths, start=1):
        annotator = path.parent.name or f"annotator_{index}"
        for row in read_csv(path):
            key = f"{record_type}:{row.get('event_id', '')}:{row.get(id_field, '')}"
            votes.setdefault(key, {"record_type": record_type, "event_id": row.get("event_id", ""), "record_id": row.get(id_field, ""), "votes": {}})
            votes[key]["votes"][annotator] = normalize_decision(row.get("review_decision"))
    return votes


def agreement_report(votes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    matrix = []
    for item in votes.values():
        counts = Counter(vote for vote in item["votes"].values() if vote)
        matrix.append([counts.get(label, 0) for label in DECISION_LABELS])
    fleiss = fleiss_kappa(matrix)
    alpha = krippendorff_alpha_nominal([list(item["votes"].values()) for item in votes.values()])
    return {
        "items": len(matrix),
        "fleiss_kappa": round(fleiss, 4) if fleiss is not None else None,
        "krippendorff_alpha": round(alpha, 4) if alpha is not None else None,
        "meets_target": bool(fleiss is not None and fleiss >= 0.80),
        "meets_minimum": bool(fleiss is not None and fleiss >= 0.70),
    }


def fleiss_kappa(matrix: list[list[int]]) -> float | None:
    if not matrix:
        return None
    n = sum(matrix[0])
    if n <= 1 or any(sum(row) != n for row in matrix):
        return None
    items = len(matrix)
    category_totals = [sum(row[j] for row in matrix) for j in range(len(matrix[0]))]
    p_j = [total / (items * n) for total in category_totals]
    p_bar_e = sum(p * p for p in p_j)
    p_i = [(sum(count * count for count in row) - n) / (n * (n - 1)) for row in matrix]
    p_bar = sum(p_i) / items
    if p_bar_e == 1:
        return 1.0
    return (p_bar - p_bar_e) / (1 - p_bar_e)


def krippendorff_alpha_nominal(votes_by_item: list[list[str]]) -> float | None:
    pairs = []
    label_counts = Counter()
    for votes in votes_by_item:
        labels = [vote for vote in votes if vote]
        label_counts.update(labels)
        for i, left in enumerate(labels):
            for right in labels[i + 1:]:
                pairs.append((left, right))
    if not pairs:
        return None
    observed = sum(1 for left, right in pairs if left != right) / len(pairs)
    total = sum(label_counts.values())
    if total <= 1:
        return None
    expected = 1 - sum((count / total) ** 2 for count in label_counts.values())
    if expected == 0:
        return 1.0
    return 1 - observed / expected


def conflict_rows(votes: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for item in votes.values():
        labels = list(item["votes"].values())
        if len(set(labels)) <= 1:
            continue
        row = {
            "record_type": item["record_type"],
            "event_id": item["event_id"],
            "record_id": item["record_id"],
            "vote_distribution": json.dumps(dict(Counter(labels)), ensure_ascii=False),
            "adjudication_status": "needs_adjudication",
            "final_decision": "",
            "adjudicator_id": "",
            "adjudicator_note": "",
        }
        row.update({annotator: decision for annotator, decision in sorted(item["votes"].items())})
        rows.append(row)
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    return "\n".join([
        "# Independent Annotation IAA Report",
        "",
        f"- tuple_iaa: {report['tuple_iaa']}",
        f"- chain_iaa: {report['chain_iaa']}",
        f"- conflict_count: {report['conflict_count']}",
        "",
        "Rows in `adjudication_conflict_sheet.csv` must be resolved by an expert adjudicator before conversion to human gold.",
    ]) + "\n"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def normalize_decision(value: Any) -> str:
    value = str(value or "").strip()
    return value if value in DECISION_LABELS else "uncertain"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if rows:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    else:
        fieldnames = []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
