#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build and audit independent human adjudication sheets."""

from __future__ import annotations

import argparse
import csv
import json
import re
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
    elif args.command == "audit":
        report = audit_independent_annotations(
            tuple_sheets=[Path(item) for item in split_csv(args.tuple_sheets)],
            chain_sheets=[Path(item) for item in split_csv(args.chain_sheets)],
            output_dir=output_dir,
        )
    else:
        report = materialize_consensus_sheets(
            tuple_sheets=[Path(item) for item in split_csv(args.tuple_sheets)],
            chain_sheets=[Path(item) for item in split_csv(args.chain_sheets)],
            output_dir=output_dir,
            tuple_output=Path(args.tuple_output) if args.tuple_output else None,
            chain_output=Path(args.chain_output) if args.chain_output else None,
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

    consensus = sub.add_parser("consensus", help="Write final consensus sheets when annotator rows agree.")
    consensus.add_argument("--tuple-sheets", required=True, help="Comma-separated completed tuple CSVs.")
    consensus.add_argument("--chain-sheets", required=True, help="Comma-separated completed chain CSVs.")
    consensus.add_argument("--output-dir", default="data/pubevent_soa_lite/human_gold_v2")
    consensus.add_argument("--tuple-output", default="")
    consensus.add_argument("--chain-output", default="")
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
        tuple_out = annotator_dir / tuple_sheet_filename(annotator)
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
    independence = {
        "tuple": independence_audit(tuple_sheets, "tuple"),
        "chain": independence_audit(chain_sheets, "chain"),
    }
    tuple_report["valid_for_iaa"] = bool(independence["tuple"]["valid_for_iaa"])
    chain_report["valid_for_iaa"] = bool(independence["chain"]["valid_for_iaa"])
    iaa_valid_for_claims = tuple_report["valid_for_iaa"] and chain_report["valid_for_iaa"]
    if not tuple_report["valid_for_iaa"]:
        tuple_report["meets_target"] = False
        tuple_report["meets_minimum"] = False
    if not chain_report["valid_for_iaa"]:
        chain_report["meets_target"] = False
        chain_report["meets_minimum"] = False
    conflicts = conflict_rows(tuple_votes) + conflict_rows(chain_votes)
    write_csv(output_dir / "adjudication_conflict_sheet.csv", conflicts)
    report = {
        "status": "completed" if iaa_valid_for_claims else "diagnostic_only",
        "iaa_valid_for_claims": iaa_valid_for_claims,
        "independence_audit": independence,
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


def independence_audit(paths: list[Path], record_type: str) -> dict[str, Any]:
    id_field = "tuple_id" if record_type == "tuple" else "chain_id"
    fields = (
        ("stakeholder", "opinion", "sentiment", "rationale")
        if record_type == "tuple"
        else ("event_chain", "evidence_ids")
    )
    row_sets = [read_csv(path) for path in paths]
    maps = [rows_by_key(rows, record_type, id_field, path) for rows, path in zip(row_sets, paths)]
    if not maps:
        return {"valid_for_iaa": False, "reason": "no sheets"}
    common_keys = set(maps[0])
    for row_map in maps[1:]:
        common_keys &= set(row_map)

    comparable_fields = 0
    field_diffs = 0
    statuses: list[str] = []
    for key in sorted(common_keys):
        rows = [row_map[key] for row_map in maps]
        statuses.extend(normalize_cell(row.get("adjudication_status")) for row in rows)
        for field in fields:
            values = [normalize_cell(row.get(field)) for row in rows]
            if not any(values):
                continue
            comparable_fields += 1
            if len(set(values)) > 1:
                field_diffs += 1

    all_rows_adjudicated_final = bool(statuses) and all(status == "adjudicated_final" for status in statuses)
    identical_adjudicated_copies = (
        comparable_fields > 0 and field_diffs == 0 and all_rows_adjudicated_final
    )
    return {
        "record_type": record_type,
        "shared_items": len(common_keys),
        "compared_fields": list(fields),
        "comparable_fields": comparable_fields,
        "field_diffs": field_diffs,
        "all_rows_adjudicated_final": all_rows_adjudicated_final,
        "identical_adjudicated_copies": identical_adjudicated_copies,
        "valid_for_iaa": not identical_adjudicated_copies,
        "warning": (
            "annotator sheets appear to be identical adjudicated-final copies; "
            "raw kappa is diagnostic only and must not be cited as inter-annotator agreement"
            if identical_adjudicated_copies
            else ""
        ),
    }


def materialize_consensus_sheets(
    *,
    tuple_sheets: list[Path],
    chain_sheets: list[Path],
    output_dir: Path,
    tuple_output: Path | None = None,
    chain_output: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tuple_output = tuple_output or output_dir / "adjudicated_human_tuple_sheet.csv"
    chain_output = chain_output or output_dir / "adjudicated_human_chain_sheet.csv"
    tuple_rows = consensus_rows(tuple_sheets, "tuple")
    chain_rows = consensus_rows(chain_sheets, "chain")
    write_csv(tuple_output, tuple_rows)
    write_csv(chain_output, chain_rows)
    return {
        "status": "completed",
        "reviewer_id": "consensus_ABC",
        "tuple_rows": len(tuple_rows),
        "chain_rows": len(chain_rows),
        "outputs": {
            "tuple_sheet": str(tuple_output),
            "chain_sheet": str(chain_output),
        },
    }


def consensus_rows(paths: list[Path], record_type: str) -> list[dict[str, str]]:
    if len(paths) < 2:
        raise ValueError("at least two independent annotator sheets are required")
    id_field = "tuple_id" if record_type == "tuple" else "chain_id"
    row_sets = [read_csv(path) for path in paths]
    maps = [rows_by_key(rows, record_type, id_field, path) for rows, path in zip(row_sets, paths)]
    first_keys = list(maps[0])
    first_key_set = set(first_keys)
    for path, row_map in zip(paths[1:], maps[1:]):
        key_set = set(row_map)
        if key_set != first_key_set:
            missing = sorted(first_key_set - key_set)[:5]
            extra = sorted(key_set - first_key_set)[:5]
            raise ValueError(f"{path}: row key mismatch; missing={missing}; extra={extra}")
    output = []
    fields = consensus_compare_fields(record_type)
    for key in first_keys:
        rows = [row_map[key] for row_map in maps]
        decisions = [normalize_decision(row.get("review_decision")) for row in rows]
        if len(set(decisions)) != 1:
            raise ValueError(f"{key}: conflicting review_decision values {decisions}")
        statuses = [str(row.get("adjudication_status") or "").strip() for row in rows]
        if any(status != "adjudicated_final" for status in statuses):
            raise ValueError(f"{key}: all rows must be adjudicated_final, got {statuses}")
        for field in fields:
            values = [normalize_cell(row.get(field)) for row in rows]
            if len(set(values)) != 1:
                raise ValueError(f"{key}: conflicting {field} values")
        item = dict(rows[0])
        item["review_decision"] = decisions[0]
        item["reviewer_id"] = "consensus_ABC"
        if "annotator_id" in item:
            item["annotator_id"] = "consensus_ABC"
        item["adjudication_status"] = "adjudicated_final"
        if "reviewer_note" in item:
            item["reviewer_note"] = consensus_note(rows)
        output.append(item)
    return output


def rows_by_key(rows: list[dict[str, str]], record_type: str, id_field: str, path: Path) -> dict[str, dict[str, str]]:
    row_map: dict[str, dict[str, str]] = {}
    for row in rows:
        key = f"{record_type}:{row.get('event_id', '')}:{row.get(id_field, '')}"
        if key in row_map:
            raise ValueError(f"{path}: duplicate row key {key}")
        row_map[key] = row
    return row_map


def consensus_compare_fields(record_type: str) -> tuple[str, ...]:
    if record_type == "tuple":
        return (
            "event_id",
            "tuple_id",
            "stakeholder",
            "opinion",
            "sentiment",
            "rationale",
            "evidence_ids",
            "support_label",
            "review_decision",
            "revised_stakeholder",
            "revised_opinion",
            "revised_sentiment",
            "revised_rationale",
            "revised_evidence_ids",
        )
    return (
        "event_id",
        "chain_id",
        "event_chain",
        "evidence_ids",
        "review_decision",
        "revised_event_chain",
        "revised_evidence_ids",
    )


def normalize_cell(value: Any) -> str:
    return str(value or "").strip()


def consensus_note(rows: list[dict[str, str]]) -> str:
    notes = list(dict.fromkeys(str(row.get("reviewer_note") or "").strip() for row in rows if str(row.get("reviewer_note") or "").strip()))
    return " / ".join(notes)


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


def tuple_sheet_filename(annotator: str) -> str:
    return f"{annotator_file_prefix(annotator)}_tuple_adjudication_sheet.csv"


def annotator_file_prefix(annotator: str) -> str:
    value = str(annotator or "").strip()
    if value.startswith("annotator_") and value[len("annotator_"):]:
        suffix = value[len("annotator_"):]
        if len(suffix) == 1 and suffix.isalpha():
            return f"human{suffix.upper()}"
        return safe_filename_token(suffix)
    return safe_filename_token(value) or "annotator"


def safe_filename_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    return token or "annotator"


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
        f"- status: {report['status']}",
        f"- iaa_valid_for_claims: {report.get('iaa_valid_for_claims')}",
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
