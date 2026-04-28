"""Validate EpiSOA JSONL datasets before paper experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}
MOCK_MARKERS = ("mock", "example.org", "fictional")


def load_jsonl(path: Path, label: str, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        errors.append(f"{label} file not found: {path}")
        return records

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}:{line_number} is not valid JSON: {exc.msg}")
            continue
        if not isinstance(record, dict):
            errors.append(f"{label}:{line_number} must be a JSON object")
            continue
        records.append(record)
    return records


def find_duplicate_ids(records: list[dict[str, Any]], id_key: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        value = record.get(id_key)
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def collect_event_names(events: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for event in events:
        for key in ("target_event", "event", "title", "name"):
            value = event.get(key)
            if isinstance(value, str) and value:
                names.add(value)
    return names


def extract_evidence_ids_from_tuple(record: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("evidence_ids", "EvidenceIDs", "annotated_evidence_ids"):
        value = record.get(key)
        if isinstance(value, list):
            ids.extend(str(item) for item in value if item)
        elif isinstance(value, str) and value:
            ids.extend(part.strip() for part in value.split(";") if part.strip())

    evidence = record.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                evidence_id = item.get("evidence_id")
                if isinstance(evidence_id, str) and evidence_id:
                    ids.append(evidence_id)
            elif isinstance(item, str) and item:
                ids.append(item)
    return ids


def contains_marker(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in MOCK_MARKERS)
    if isinstance(value, dict):
        return any(contains_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_marker(item) for item in value)
    return False


def validate_dataset(
    events_path: str | Path,
    evidence_path: str | Path,
    gold_tuples_path: str | Path,
    gold_event_chains_path: str | Path,
) -> dict[str, Any]:
    events_path = Path(events_path)
    evidence_path = Path(evidence_path)
    gold_tuples_path = Path(gold_tuples_path)
    gold_event_chains_path = Path(gold_event_chains_path)
    errors: list[str] = []
    warnings: list[str] = []

    events = load_jsonl(events_path, "events", errors)
    evidence = load_jsonl(evidence_path, "evidence", errors)
    gold_tuples = load_jsonl(gold_tuples_path, "gold_tuples", errors)
    gold_event_chains = load_jsonl(gold_event_chains_path, "gold_event_chains", errors)

    if not events:
        warnings.append("events is empty; formal paper experiments need human-curated events")
    if not evidence:
        warnings.append("evidence is empty; formal paper experiments need human-curated evidence")
    if not gold_tuples:
        warnings.append("gold_tuples is empty; formal paper experiments need human annotations")
    if not gold_event_chains:
        warnings.append("gold_event_chains is empty; formal paper experiments need event-chain annotations")

    for duplicate in find_duplicate_ids(events, "event_id"):
        errors.append(f"duplicate event_id: {duplicate}")
    for duplicate in find_duplicate_ids(evidence, "evidence_id"):
        errors.append(f"duplicate evidence_id: {duplicate}")

    event_ids = {record["event_id"] for record in events if isinstance(record.get("event_id"), str)}
    event_names = collect_event_names(events)
    evidence_ids = {record["evidence_id"] for record in evidence if isinstance(record.get("evidence_id"), str)}

    for index, record in enumerate(events, start=1):
        if not isinstance(record.get("event_id"), str) or not record.get("event_id"):
            errors.append(f"events:{index} missing non-empty event_id")

    for index, record in enumerate(evidence, start=1):
        evidence_id = record.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            errors.append(f"evidence:{index} missing non-empty evidence_id")
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or event_id not in event_ids:
            errors.append(f"evidence:{index} references unknown event_id: {event_id!r}")

    for index, record in enumerate(gold_tuples, start=1):
        event_id = record.get("event_id")
        event_name = record.get("event")
        if isinstance(event_id, str) and event_id:
            if event_id not in event_ids:
                errors.append(f"gold_tuples:{index} references unknown event_id: {event_id!r}")
        elif isinstance(event_name, str) and event_name:
            if event_name not in event_names:
                errors.append(f"gold_tuples:{index} references unknown event: {event_name!r}")
        else:
            errors.append(f"gold_tuples:{index} missing event_id or event")

        sentiment = record.get("sentiment")
        if sentiment not in ALLOWED_SENTIMENTS:
            errors.append(f"gold_tuples:{index} invalid sentiment: {sentiment!r}")

        event_chain = record.get("event_chain")
        if not isinstance(event_chain, list) or not event_chain or not all(isinstance(item, str) and item for item in event_chain):
            errors.append(f"gold_tuples:{index} event_chain must be a non-empty list of strings")

        support_score = record.get("support_score")
        if not isinstance(support_score, (int, float)) or isinstance(support_score, bool) or not 0 <= support_score <= 1:
            errors.append(f"gold_tuples:{index} support_score must be between 0 and 1")

        if not isinstance(record.get("verified"), bool):
            errors.append(f"gold_tuples:{index} verified must be bool")

        tuple_evidence_ids = extract_evidence_ids_from_tuple(record)
        if not tuple_evidence_ids:
            errors.append(f"gold_tuples:{index} must reference at least one evidence_id")
        for evidence_id in tuple_evidence_ids:
            if evidence_id not in evidence_ids:
                errors.append(f"gold_tuples:{index} references unknown evidence_id: {evidence_id!r}")

    for index, record in enumerate(gold_event_chains, start=1):
        event_chain = record.get("event_chain")
        if not isinstance(event_chain, list) or not event_chain or not all(isinstance(item, str) and item for item in event_chain):
            errors.append(f"gold_event_chains:{index} event_chain must be a non-empty list of strings")

    has_mock_marker = any(
        contains_marker(record)
        for record in [*events, *evidence, *gold_tuples, *gold_event_chains]
    )
    if has_mock_marker:
        warnings.append("dataset contains mock/example.org/fictional marker text")

    is_nonempty = bool(events and evidence and gold_tuples and gold_event_chains)
    return {
        "dataset_path": str(events_path.parent),
        "num_events": len(events),
        "num_evidence": len(evidence),
        "num_gold_tuples": len(gold_tuples),
        "num_gold_event_chains": len(gold_event_chains),
        "is_formal_dataset": bool(is_nonempty and not errors and not has_mock_marker),
        "errors": errors,
        "warnings": warnings,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an EpiSOA dataset.")
    parser.add_argument("--events", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--gold-tuples", required=True)
    parser.add_argument("--gold-event-chains", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = validate_dataset(
        events_path=args.events,
        evidence_path=args.evidence,
        gold_tuples_path=args.gold_tuples,
        gold_event_chains_path=args.gold_event_chains,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote dataset validation report: {output_path}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
