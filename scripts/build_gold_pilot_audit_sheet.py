"""Build a human audit sheet for LLM gold preannotation pilot outputs."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl


DEFAULT_TUPLES = Path("data/pubevent_soa_lite/annotation/llm_gold_tuples.jsonl")
DEFAULT_CHAINS = Path("data/pubevent_soa_lite/annotation/llm_gold_event_chains.jsonl")
DEFAULT_AUDIT = Path("data/pubevent_soa_lite/annotation/llm_preannotation_audit.jsonl")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_OUTPUT = Path("data/pubevent_soa_lite/annotation/gold_pilot_audit_sheet.csv")

FIELDNAMES = [
    "event_id",
    "tuple_id",
    "stakeholder",
    "opinion",
    "sentiment",
    "rationale",
    "evidence_ids",
    "supporting_evidence_text",
    "tuple_generation_status",
    "chain_generation_status",
    "preannotation_note",
    "human_judgment",
    "error_type",
    "corrected_stakeholder",
    "corrected_opinion",
    "corrected_sentiment",
    "corrected_rationale",
    "corrected_evidence_ids",
    "guideline_change_needed",
    "prompt_change_needed",
    "notes",
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = build_audit_rows(
        tuples_path=Path(args.tuples),
        chains_path=Path(args.chains),
        audit_path=Path(args.audit),
        evidence_path=Path(args.evidence),
        events_path=Path(args.events),
        event_ids=parse_event_ids(args.event_ids),
        max_events=args.max_events,
    )
    write_csv(Path(args.output), rows)
    print(f"wrote {len(rows)} pilot audit rows to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a pilot audit CSV for LLM gold preannotation quality review.")
    parser.add_argument("--tuples", default=str(DEFAULT_TUPLES))
    parser.add_argument("--chains", default=str(DEFAULT_CHAINS))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--event-ids", default="")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser


def build_audit_rows(
    *,
    tuples_path: Path,
    chains_path: Path,
    audit_path: Path,
    evidence_path: Path,
    events_path: Path,
    event_ids: list[str] | None = None,
    max_events: int | None = None,
) -> list[dict[str, Any]]:
    events = select_events(load_optional_jsonl(events_path), event_ids=event_ids, max_events=max_events)
    tuples_by_event = group_by_event(load_optional_jsonl(tuples_path))
    chains_by_event = group_by_event(load_optional_jsonl(chains_path))
    audit_by_event_task = latest_audit_by_event_task(load_optional_jsonl(audit_path))
    evidence_index = {str(row.get("evidence_id")): row for row in load_optional_jsonl(evidence_path) if row.get("evidence_id")}

    rows: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        event_tuples = tuples_by_event.get(event_id, [])
        tuple_audit = audit_by_event_task.get((event_id, "tuple"), {})
        chain_audit = audit_by_event_task.get((event_id, "chain"), {})
        tuple_status = generation_status(tuple_audit, has_candidates=bool(event_tuples))
        chain_status = generation_status(chain_audit, has_candidates=bool(chains_by_event.get(event_id, [])))
        note = preannotation_note(tuple_audit, chain_audit, chains_by_event.get(event_id, []))
        if not event_tuples:
            rows.append(blank_row(event_id, tuple_status, chain_status, note))
            continue
        for index, item in enumerate(event_tuples, start=1):
            evidence_ids = normalize_ids(item.get("evidence_ids"))
            rows.append(
                {
                    "event_id": event_id,
                    "tuple_id": tuple_id(item, index),
                    "stakeholder": item.get("stakeholder", ""),
                    "opinion": item.get("opinion", ""),
                    "sentiment": item.get("sentiment", ""),
                    "rationale": item.get("rationale", ""),
                    "evidence_ids": ";".join(evidence_ids),
                    "supporting_evidence_text": supporting_text(evidence_ids, evidence_index),
                    "tuple_generation_status": "success",
                    "chain_generation_status": chain_status,
                    "preannotation_note": note,
                    "human_judgment": "",
                    "error_type": "",
                    "corrected_stakeholder": "",
                    "corrected_opinion": "",
                    "corrected_sentiment": "",
                    "corrected_rationale": "",
                    "corrected_evidence_ids": "",
                    "guideline_change_needed": "",
                    "prompt_change_needed": "",
                    "notes": chain_note(chains_by_event.get(event_id, [])),
                }
            )
    return rows


def load_optional_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def parse_event_ids(value: str) -> list[str] | None:
    ids = [item.strip() for item in value.split(",") if item.strip()]
    return ids or None


def select_events(
    events: list[dict[str, Any]],
    *,
    event_ids: list[str] | None,
    max_events: int | None,
) -> list[dict[str, Any]]:
    allowed = set(event_ids or [])
    selected = [event for event in events if not allowed or str(event.get("event_id") or "") in allowed]
    return selected[:max_events] if max_events is not None else selected


def group_by_event(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("event_id") or "")].append(row)
    return grouped


def latest_audit_by_event_task(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        event_id = str(row.get("event_id") or "")
        task = str(row.get("task_type") or row.get("task") or "")
        if event_id and task:
            latest[(event_id, task)] = row
    return latest


def generation_status(audit: dict[str, Any], *, has_candidates: bool) -> str:
    if has_candidates:
        return "success"
    if not audit:
        return "not_run"
    request_status = str(audit.get("request_status") or "")
    parse_status = str(audit.get("parse_status") or "")
    error_type = str(audit.get("error_type") or "")
    num_candidates = int(audit.get("num_candidates") or 0)
    if request_status in {"failed", "error"} and (error_type.startswith("api_") or "timeout" in error_type):
        return "api_failure"
    if parse_status == "failed":
        return "parse_failure"
    if request_status in {"ok", "success"} and parse_status in {"parsed", "success"} and num_candidates == 0:
        return "no_candidate"
    return "not_run"


def preannotation_note(
    tuple_audit: dict[str, Any],
    chain_audit: dict[str, Any],
    chains: list[dict[str, Any]],
) -> str:
    parts = []
    if tuple_audit.get("error_message"):
        parts.append(f"tuple_error={tuple_audit.get('error_type', '')}: {tuple_audit.get('error_message', '')}")
    if tuple_audit.get("warning"):
        parts.append(f"tuple_warning={tuple_audit.get('warning')}")
    if chain_audit.get("error_message"):
        parts.append(f"chain_error={chain_audit.get('error_type', '')}: {chain_audit.get('error_message', '')}")
    if chain_audit.get("warning"):
        parts.append(f"chain_warning={chain_audit.get('warning')}")
    if chains:
        parts.append(chain_note(chains))
    return " | ".join(parts)


def normalize_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.replace(",", ";").replace("|", ";").split(";") if item.strip()]


def tuple_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("candidate_id") or row.get("tuple_id") or row.get("gold_tuple_id") or f"tuple_{index:03d}")


def supporting_text(evidence_ids: list[str], evidence_index: dict[str, dict[str, Any]]) -> str:
    parts = []
    for evidence_id in evidence_ids:
        text = " ".join(str(evidence_index.get(evidence_id, {}).get("text", "")).split())
        parts.append(f"{evidence_id}: {text[:500]}")
    return "\n".join(parts)


def chain_note(chains: list[dict[str, Any]]) -> str:
    if not chains:
        return ""
    return f"candidate_chains={len(chains)}"


def blank_row(event_id: str, tuple_status: str = "not_run", chain_status: str = "not_run", note: str = "") -> dict[str, str]:
    row = {field: "" for field in FIELDNAMES}
    row["event_id"] = event_id
    row["tuple_generation_status"] = tuple_status
    row["chain_generation_status"] = chain_status
    row["preannotation_note"] = note
    if tuple_status == "no_candidate":
        row["human_judgment"] = "missing_gold_tuple"
        row["error_type"] = "missing_tuple"
    elif tuple_status == "parse_failure":
        row["error_type"] = "parse_failure"
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


if __name__ == "__main__":
    raise SystemExit(main())
