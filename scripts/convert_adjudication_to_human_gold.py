#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convert reviewed adjudication sheets into human gold JSONL files."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("data/pubevent_soa_lite/human_gold_v1")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
VALID_DECISIONS = {"accept", "revise", "drop", "add_missing", "uncertain"}
VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}
VALID_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "insufficient_evidence", ""}
FINAL_ADJUDICATION_STATUS = "adjudicated_final"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tuple_sheet = Path(args.tuple_sheet)
    chain_sheet = Path(args.chain_sheet)
    output_dir = Path(args.output_dir)
    if args.pilot:
        if tuple_sheet == DEFAULT_OUTPUT_DIR / "human_tuple_adjudication_sheet.csv":
            tuple_sheet = output_dir / "human_tuple_adjudication_sheet_pilot5.csv"
        if chain_sheet == DEFAULT_OUTPUT_DIR / "human_chain_adjudication_sheet.csv":
            chain_sheet = output_dir / "human_chain_adjudication_sheet_pilot5.csv"
    summary = convert_adjudication_to_human_gold(
        tuple_sheet=tuple_sheet,
        chain_sheet=chain_sheet,
        evidence_path=Path(args.evidence),
        events_path=Path(args.events),
        output_dir=output_dir,
        pilot=args.pilot,
        dataset_version=args.dataset_version,
        include_evidence_spans=args.include_evidence_spans,
        iaa_report_path=Path(args.iaa_report) if args.iaa_report else None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert human adjudication CSVs to human gold JSONL.")
    parser.add_argument("--tuple-sheet", default=str(DEFAULT_OUTPUT_DIR / "human_tuple_adjudication_sheet.csv"))
    parser.add_argument("--chain-sheet", default=str(DEFAULT_OUTPUT_DIR / "human_chain_adjudication_sheet.csv"))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--pilot", action="store_true", help="Write pilot_human_gold_* outputs instead of formal human_gold_v1 outputs.")
    parser.add_argument(
        "--dataset-version",
        choices=("v1", "v2"),
        default="v1",
        help="Output file suffix and manifest dataset version.",
    )
    parser.add_argument(
        "--include-evidence-spans",
        action="store_true",
        help="Populate tuple evidence_spans from canonical evidence text.",
    )
    parser.add_argument(
        "--iaa-report",
        default="",
        help="Independent annotation IAA report to embed in tuple annotation_provenance.annotation_quality.",
    )
    return parser


def convert_adjudication_to_human_gold(
    *,
    tuple_sheet: Path,
    chain_sheet: Path,
    evidence_path: Path,
    events_path: Path,
    output_dir: Path,
    pilot: bool = False,
    dataset_version: str = "v1",
    include_evidence_spans: bool = False,
    iaa_report_path: Path | None = None,
) -> dict[str, Any]:
    tuple_rows = read_csv(tuple_sheet)
    chain_rows = read_csv(chain_sheet)
    evidence = read_jsonl(evidence_path)
    events = read_jsonl(events_path)
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}
    event_ids = {str(row.get("event_id")) for row in events if row.get("event_id")}

    annotation_quality = load_annotation_quality(iaa_report_path) if iaa_report_path else None
    gold_tuples, tuple_log = convert_tuple_rows(
        tuple_rows,
        evidence_by_id,
        event_ids,
        include_evidence_spans=include_evidence_spans,
        annotation_quality=annotation_quality,
    )
    gold_chains, chain_log = convert_chain_rows(chain_rows, evidence_by_id, event_ids)
    validate_unique_ids(gold_tuples, id_field="tuple_id", object_name="tuple")
    validate_unique_ids(gold_chains, id_field="chain_id", object_name="chain")

    output_dir.mkdir(parents=True, exist_ok=True)
    file_prefix = "pilot_human_gold" if pilot else "human_gold"
    tuples_out = output_dir / f"{file_prefix}_tuples_{dataset_version}.jsonl"
    chains_out = output_dir / f"{file_prefix}_event_chains_{dataset_version}.jsonl"
    manifest_out = output_dir / f"{file_prefix}_manifest_{dataset_version}.json"
    if pilot:
        rejected_out = output_dir / ("pilot_rejected_or_uncertain_log.csv" if dataset_version == "v1" else f"pilot_rejected_or_uncertain_log_{dataset_version}.csv")
    else:
        rejected_out = output_dir / ("rejected_or_uncertain_log.csv" if dataset_version == "v1" else f"rejected_or_uncertain_log_{dataset_version}.csv")
    write_jsonl(tuples_out, gold_tuples)
    write_jsonl(chains_out, gold_chains)
    write_csv(rejected_out, tuple_log + chain_log, [
        "record_type", "event_id", "record_id", "review_decision", "reason", "reviewer_id", "reviewer_note",
    ])

    tuple_decisions = Counter(normalize_decision(row.get("review_decision")) for row in tuple_rows)
    chain_decisions = Counter(normalize_decision(row.get("review_decision")) for row in chain_rows)
    dataset_level = "pilot_human_gold" if pilot else "human_gold"
    manifest = {
        "dataset_name": f"pubevent_soa_lite_{dataset_level}_{dataset_version}",
        "dataset_level": dataset_level,
        "dataset_version": dataset_version,
        "source": "pilot_human_adjudication" if pilot else "human_adjudication",
        "pilot": pilot,
        "human_verified": True,
        "ready_for_main_experiment": False,
        "original_files_modified": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "tuple_sheet": str(tuple_sheet),
            "chain_sheet": str(chain_sheet),
            "canonical_evidence": str(evidence_path),
            "events": str(events_path),
            "iaa_report": str(iaa_report_path) if iaa_report_path else "",
        },
        "outputs": {
            "human_gold_tuples": str(tuples_out),
            "human_gold_event_chains": str(chains_out),
            "human_gold_manifest": str(manifest_out),
            "rejected_or_uncertain_log": str(rejected_out),
        },
        "counts": {
            "human_gold_tuples": len(gold_tuples),
            "human_gold_event_chains": len(gold_chains),
            "rejected_or_uncertain_rows": len(tuple_log) + len(chain_log),
            "tuples_with_evidence_spans": sum(1 for row in gold_tuples if row.get("evidence_spans")),
        },
        "paper_grade_metadata": {
            "include_evidence_spans": include_evidence_spans,
            "annotation_quality_embedded": annotation_quality is not None,
        },
        "decision_counts": {
            "tuples": dict(tuple_decisions),
            "chains": dict(chain_decisions),
        },
        "notes": [
            "ready_for_main_experiment is set by scripts/audit_human_gold.py and remains false until total_issues=0.",
            "uncertain and drop rows are excluded from human_gold outputs.",
        ],
    }
    write_json(manifest_out, manifest)
    return manifest


def convert_tuple_rows(
    rows: list[dict[str, str]],
    evidence_by_id: dict[str, dict[str, Any]],
    event_ids: set[str],
    *,
    include_evidence_spans: bool = False,
    annotation_quality: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    output: list[dict[str, Any]] = []
    log: list[dict[str, str]] = []
    event_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        decision = normalize_decision(row.get("review_decision"))
        record_id = row.get("tuple_id", "")
        event_id = row.get("event_id", "")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid review_decision for tuple {record_id}: {decision}")
        if normalize_status(row.get("adjudication_status")) != FINAL_ADJUDICATION_STATUS:
            log.append(log_row("tuple", event_id, record_id, decision, "excluded_by_not_adjudicated_final", row))
            continue
        if decision in {"drop", "uncertain"}:
            log.append(log_row("tuple", event_id, record_id, decision, f"excluded_by_{decision}", row))
            continue
        if decision == "accept":
            candidate = {
                "tuple_id": record_id,
                "event_id": event_id,
                "stakeholder": row.get("stakeholder", ""),
                "opinion": row.get("opinion", ""),
                "sentiment": row.get("sentiment", ""),
                "rationale": row.get("rationale", ""),
                "evidence_ids": parse_ids(row.get("evidence_ids")),
                "support_label": row.get("support_label", "supported") or "supported",
                "source_silver_tuple_id": record_id,
                "review_decision": decision,
            }
        elif decision == "revise":
            candidate = {
                "tuple_id": record_id,
                "event_id": event_id,
                "stakeholder": row.get("revised_stakeholder", ""),
                "opinion": row.get("revised_opinion", ""),
                "sentiment": row.get("revised_sentiment", ""),
                "rationale": row.get("revised_rationale", ""),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids")),
                "support_label": row.get("support_label", "supported") or "supported",
                "source_silver_tuple_id": record_id,
                "review_decision": decision,
            }
        else:
            event_counts[event_id] += 1
            new_id = record_id or f"HG_{event_id}_{event_counts[event_id]:03d}"
            candidate = {
                "tuple_id": new_id,
                "event_id": event_id,
                "stakeholder": row.get("revised_stakeholder") or row.get("stakeholder", ""),
                "opinion": row.get("revised_opinion") or row.get("opinion", ""),
                "sentiment": row.get("revised_sentiment") or row.get("sentiment", ""),
                "rationale": row.get("revised_rationale") or row.get("rationale", ""),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids") or row.get("evidence_ids")),
                "support_label": row.get("support_label", "supported") or "supported",
                "source_silver_tuple_id": record_id,
                "review_decision": decision,
            }
        validate_tuple(candidate, evidence_by_id, event_ids)
        candidate["annotation_provenance"] = provenance(row, decision)
        if annotation_quality:
            candidate["annotation_provenance"]["annotation_quality"] = dict(annotation_quality)
        if include_evidence_spans:
            candidate["evidence_spans"] = evidence_spans_for_tuple(candidate["evidence_ids"], evidence_by_id)
        output.append(candidate)
    return output, log


def convert_chain_rows(
    rows: list[dict[str, str]],
    evidence_by_id: dict[str, dict[str, Any]],
    event_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    output: list[dict[str, Any]] = []
    log: list[dict[str, str]] = []
    event_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        decision = normalize_decision(row.get("review_decision"))
        chain_id = row.get("chain_id", "")
        event_id = row.get("event_id", "")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid review_decision for chain {chain_id}: {decision}")
        if normalize_status(row.get("adjudication_status")) != FINAL_ADJUDICATION_STATUS:
            log.append(log_row("chain", event_id, chain_id, decision, "excluded_by_not_adjudicated_final", row))
            continue
        if decision in {"drop", "uncertain"}:
            log.append(log_row("chain", event_id, chain_id, decision, f"excluded_by_{decision}", row))
            continue
        if decision == "accept":
            candidate = {
                "chain_id": chain_id,
                "event_id": event_id,
                "event_chain": parse_chain(row.get("event_chain")),
                "evidence_ids": parse_ids(row.get("evidence_ids")),
                "source_silver_chain_id": chain_id,
                "review_decision": decision,
            }
        elif decision == "revise":
            candidate = {
                "chain_id": chain_id,
                "event_id": event_id,
                "event_chain": parse_chain(row.get("revised_event_chain")),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids")),
                "source_silver_chain_id": chain_id,
                "review_decision": decision,
            }
        else:
            event_counts[event_id] += 1
            new_id = chain_id or f"HGC_{event_id}_{event_counts[event_id]:03d}"
            candidate = {
                "chain_id": new_id,
                "event_id": event_id,
                "event_chain": parse_chain(row.get("revised_event_chain") or row.get("event_chain")),
                "evidence_ids": parse_ids(row.get("revised_evidence_ids") or row.get("evidence_ids")),
                "source_silver_chain_id": chain_id,
                "review_decision": decision,
            }
        validate_chain(candidate, evidence_by_id, event_ids)
        candidate["annotation_provenance"] = provenance(row, decision)
        output.append(candidate)
    return output, log


def load_annotation_quality(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    report = json.loads(path.read_text(encoding="utf-8"))
    if int(report.get("conflict_count", 0) or 0) > 0:
        raise ValueError(f"{path}: conflict_count must be 0 before embedding IAA quality")
    tuple_iaa = report.get("tuple_iaa") if isinstance(report.get("tuple_iaa"), dict) else {}
    fleiss = coerce_float(tuple_iaa.get("fleiss_kappa"))
    alpha = coerce_float(tuple_iaa.get("krippendorff_alpha"))
    if fleiss is None:
        raise ValueError(f"{path}: tuple_iaa.fleiss_kappa is required")
    quality = {
        "cohen_kappa": fleiss,
        "tuple_cohen_kappa": fleiss,
        "support_label_cohen_kappa": fleiss,
        "fleiss_kappa": fleiss,
        "source": str(path),
    }
    if alpha is not None:
        quality["krippendorff_alpha"] = alpha
    if tuple_iaa.get("items") is not None:
        quality["items"] = int(tuple_iaa.get("items") or 0)
    return quality


def coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evidence_spans_for_tuple(evidence_ids: list[str], evidence_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence = evidence_by_id.get(str(evidence_id), {})
        existing = evidence.get("evidence_spans") if isinstance(evidence.get("evidence_spans"), list) else []
        if existing:
            for item in existing:
                if isinstance(item, dict):
                    spans.append(normalize_span(item, str(evidence_id)))
            continue
        text = str(evidence.get("text_excerpt") or evidence.get("text") or evidence.get("legacy_text") or "")
        spans.append({
            "evidence_id": str(evidence_id),
            "char_start": 0,
            "char_end": min(len(text), 500),
            "text": text[:500],
        })
    return spans


def normalize_span(row: dict[str, Any], fallback_evidence_id: str) -> dict[str, Any]:
    return {
        "evidence_id": str(row.get("evidence_id") or fallback_evidence_id),
        "char_start": int(row.get("char_start", 0) or 0),
        "char_end": int(row.get("char_end", 0) or 0),
        "text": str(row.get("text") or "")[:500],
    }


def validate_tuple(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]], event_ids: set[str]) -> None:
    prefix = f"tuple {row.get('tuple_id')}"
    if row.get("event_id") not in event_ids:
        raise ValueError(f"{prefix}: unknown event_id {row.get('event_id')}")
    for field in ("tuple_id", "stakeholder", "opinion", "rationale"):
        if not str(row.get(field) or "").strip():
            raise ValueError(f"{prefix}: missing {field}")
    if row.get("sentiment") not in VALID_SENTIMENTS:
        raise ValueError(f"{prefix}: invalid sentiment {row.get('sentiment')}")
    if row.get("support_label") not in VALID_SUPPORT_LABELS:
        raise ValueError(f"{prefix}: invalid support_label {row.get('support_label')}")
    ids = row.get("evidence_ids") or []
    if not ids:
        raise ValueError(f"{prefix}: missing evidence_ids")
    validate_evidence_ids(prefix, row.get("event_id", ""), ids, evidence_by_id)


def validate_chain(row: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]], event_ids: set[str]) -> None:
    prefix = f"chain {row.get('chain_id')}"
    if row.get("event_id") not in event_ids:
        raise ValueError(f"{prefix}: unknown event_id {row.get('event_id')}")
    if not str(row.get("chain_id") or "").strip():
        raise ValueError(f"{prefix}: missing chain_id")
    if not row.get("event_chain"):
        raise ValueError(f"{prefix}: missing event_chain")
    ids = row.get("evidence_ids") or []
    if not ids:
        raise ValueError(f"{prefix}: missing evidence_ids")
    validate_evidence_ids(prefix, row.get("event_id", ""), ids, evidence_by_id)


def validate_evidence_ids(prefix: str, event_id: str, ids: list[str], evidence_by_id: dict[str, dict[str, Any]]) -> None:
    for evidence_id in ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise ValueError(f"{prefix}: unknown evidence_id {evidence_id}")
        if str(evidence.get("event_id")) != str(event_id):
            raise ValueError(f"{prefix}: evidence_id {evidence_id} belongs to event {evidence.get('event_id')}")


def validate_unique_ids(rows: list[dict[str, Any]], *, id_field: str, object_name: str) -> None:
    seen: set[str] = set()
    for row in rows:
        value = str(row.get(id_field) or "")
        if value in seen:
            raise ValueError(f"duplicate {object_name} {id_field}: {value}")
        seen.add(value)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    backup_existing(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    backup_existing(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    backup_existing(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def backup_existing(path: Path) -> None:
    if not path.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.bak_{timestamp}"))


def normalize_decision(value: Any) -> str:
    return str(value or "").strip()


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).replace("|", ";").replace(",", ";").split(";") if item.strip()]


def parse_chain(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if not value:
        return []
    text = str(value)
    if "|||" in text:
        parts = text.split("|||")
    elif "->" in text:
        parts = text.split("->")
    else:
        parts = text.split(";")
    return [part.strip() for part in parts if part.strip()]


def provenance(row: dict[str, str], decision: str) -> dict[str, str]:
    return {
        "source": "human_adjudication",
        "review_decision": decision,
        "reviewer_id": row.get("reviewer_id", ""),
        "adjudication_status": row.get("adjudication_status", ""),
        "reviewer_note": row.get("reviewer_note", ""),
    }


def log_row(record_type: str, event_id: str, record_id: str, decision: str, reason: str, row: dict[str, str]) -> dict[str, str]:
    return {
        "record_type": record_type,
        "event_id": event_id,
        "record_id": record_id,
        "review_decision": decision,
        "reason": reason,
        "reviewer_id": row.get("reviewer_id", ""),
        "reviewer_note": row.get("reviewer_note", ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
