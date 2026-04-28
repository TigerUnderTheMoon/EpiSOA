"""Compute inter-annotator agreement for EpiSOA formal annotations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


AGREEMENT_FIELDS = [
    "stakeholder",
    "opinion",
    "sentiment",
    "rationale",
    "event_chain",
    "evidence_ids",
    "support_score",
    "verified",
]
CATEGORICAL_FIELDS = ["stakeholder", "sentiment", "verified"]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"annotation file not found: {file_path}")

    for line_number, raw_line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{file_path}:{line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{file_path}:{line_number} must be a JSON object")
        records.append(record)
    return records


def annotation_key(record: dict[str, Any], index: int) -> str:
    for key in ("tuple_id", "annotation_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value

    event_id = record.get("event_id")
    evidence_ids = normalize_value(record.get("evidence_ids") or record.get("annotated_evidence_ids"))
    if event_id and evidence_ids:
        return f"{event_id}|{evidence_ids}"
    evidence_id = record.get("evidence_id")
    if event_id and evidence_id:
        return f"{event_id}|{evidence_id}"
    return f"row-{index:05d}"


def normalize_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    normalized = {
        "key": annotation_key(record, index),
        "stakeholder": record.get("stakeholder") or record.get("annotated_stakeholder"),
        "opinion": record.get("opinion") or record.get("annotated_opinion"),
        "sentiment": record.get("sentiment") or record.get("annotated_sentiment"),
        "rationale": record.get("rationale") or record.get("annotated_rationale"),
        "event_chain": record.get("event_chain") or record.get("annotated_event_chain"),
        "evidence_ids": record.get("evidence_ids") or record.get("annotated_evidence_ids"),
        "support_score": record.get("support_score"),
        "verified": record.get("verified"),
    }
    return {key: normalize_value(value) for key, value in normalized.items()}


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.6g}"
    if isinstance(value, list):
        return ";".join(sorted(normalize_value(item) for item in value if normalize_value(item)))
    return str(value).strip()


def exact_agreement(values_a: list[str], values_b: list[str]) -> float | None:
    if not values_a:
        return None
    matches = sum(1 for left, right in zip(values_a, values_b, strict=True) if left == right)
    return matches / len(values_a)


def cohens_kappa(values_a: list[str], values_b: list[str]) -> float | None:
    if not values_a:
        return None
    labels = sorted(set(values_a) | set(values_b))
    observed = exact_agreement(values_a, values_b)
    if observed is None:
        return None

    expected = 0.0
    total = len(values_a)
    for label in labels:
        left_count = sum(1 for value in values_a if value == label)
        right_count = sum(1 for value in values_b if value == label)
        expected += (left_count / total) * (right_count / total)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def compute_agreement(annotator_a_path: str | Path, annotator_b_path: str | Path) -> dict[str, Any]:
    records_a = [normalize_record(record, index) for index, record in enumerate(load_jsonl(annotator_a_path), start=1)]
    records_b = [normalize_record(record, index) for index, record in enumerate(load_jsonl(annotator_b_path), start=1)]
    by_key_a = {record["key"]: record for record in records_a}
    by_key_b = {record["key"]: record for record in records_b}
    common_keys = sorted(set(by_key_a) & set(by_key_b))

    field_agreement: dict[str, Any] = {}
    for field in AGREEMENT_FIELDS:
        values_a = [by_key_a[key].get(field, "") for key in common_keys]
        values_b = [by_key_b[key].get(field, "") for key in common_keys]
        field_agreement[field] = {
            "exact_agreement": exact_agreement(values_a, values_b),
            "matches": sum(1 for left, right in zip(values_a, values_b, strict=True) if left == right),
            "total": len(common_keys),
        }
        if field in CATEGORICAL_FIELDS:
            field_agreement[field]["cohens_kappa"] = cohens_kappa(values_a, values_b)

    return {
        "num_annotator_a": len(records_a),
        "num_annotator_b": len(records_b),
        "num_common_items": len(common_keys),
        "missing_from_annotator_a": sorted(set(by_key_b) - set(by_key_a)),
        "missing_from_annotator_b": sorted(set(by_key_a) - set(by_key_b)),
        "field_agreement": field_agreement,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute EpiSOA annotator agreement.")
    parser.add_argument("--annotator-a", required=True)
    parser.add_argument("--annotator-b", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = compute_agreement(args.annotator_a, args.annotator_b)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "wrote agreement report: "
        f"{output_path} ({report['num_common_items']} common annotation item(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
