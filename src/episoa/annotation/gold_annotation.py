"""Gold annotation review-sheet and export utilities.

This module deliberately treats model and verifier output as pre-annotation only.
Gold rows are emitted only after explicit human review fields are present.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
SUPPORT_LABELS = {"supported", "partially_supported", "unsupported"}
STAGES = {"trigger", "diffusion", "conflict", "response", "resolution", "follow_up", "unknown"}
STAGE_ORDER = {
    "trigger": 1,
    "diffusion": 2,
    "conflict": 3,
    "response": 4,
    "resolution": 5,
    "follow_up": 6,
    "unknown": 99,
}
REVIEWED_STATUSES = {"reviewed", "adjudicated"}
ACCEPT_DECISIONS = {"accept", "approved", "revise", "revised"}
NEW_TUPLE_DECISIONS = {"accept", "approved", "revise", "revised", "add_missing", "added", ""}

TUPLE_REVIEW_FIELDS = [
    "event_id",
    "event_name",
    "tuple_id",
    "candidate_stakeholder",
    "candidate_opinion",
    "candidate_sentiment",
    "candidate_rationale",
    "candidate_evidence_ids",
    "candidate_event_chain_stage",
    "candidate_confidence",
    "verification_label",
    "verification_score",
    "verification_rationale",
    "issue_flags",
    "evidence_quotes",
    "evidence_texts",
    "chain_confidence",
    "missing_stages",
    "human_decision",
    "gold_stakeholder",
    "gold_opinion",
    "gold_sentiment",
    "gold_rationale",
    "gold_evidence_ids",
    "gold_event_chain_stage",
    "gold_support_label",
    "gold_event_chain_order",
    "gold_notes",
    "annotator_id",
    "review_status",
    "adjudication_status",
]

NEW_TUPLE_FIELDS = [
    "event_id",
    "event_name",
    "gold_stakeholder",
    "gold_opinion",
    "gold_sentiment",
    "gold_rationale",
    "gold_evidence_ids",
    "gold_event_chain_stage",
    "gold_support_label",
    "gold_event_chain_order",
    "gold_notes",
    "annotator_id",
    "review_status",
    "adjudication_status",
]

EVIDENCE_INVENTORY_FIELDS = [
    "event_id",
    "event_name",
    "evidence_id",
    "source",
    "domain",
    "url",
    "title",
    "text_excerpt",
    "candidate_stage",
    "source_type",
    "quality_score",
]

REVIEW_INSTRUCTIONS = """人工审核说明：
1. 本文件中的候选主体观点元组来自模型输出和证据忠实性验证结果。
2. 候选结果不是 gold。
3. 请逐条检查 stakeholder、opinion、sentiment、rationale、evidence_ids 和 event_chain_stage。
4. 如果候选完全正确，将 human_decision 改为 accept，review_status 改为 reviewed。
5. 如果候选部分正确但需要修正，将 human_decision 改为 revise，并修改 gold_* 字段。
6. 如果候选不应进入 gold，将 human_decision 改为 reject。
7. 如果无法判断，保留 need_review。
8. 如果发现模型遗漏的主体观点，请填写 new_tuple_template.csv。
9. 只有 reviewed/adjudicated 且 accept/revise/added 的记录会进入 gold。
10. LLM 仅用于辅助预标注，最终 gold 以人工审核结果为准。
"""


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must be a JSON object")
        rows.append(value)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def write_csv_rows(path: str | Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path = Path(path)
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


def split_cell(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    parts = text.replace("|", ";").replace(",", ";").split(";")
    return [part.strip() for part in parts if part.strip()]


def load_event_index(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("event_id", "")): row for row in events if row.get("event_id")}


def load_evidence_index(evidence_rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("evidence_id", "")): row for row in evidence_rows if row.get("evidence_id")}


def load_chain_index(chains: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("event_id", "")): row for row in chains if row.get("event_id")}


def parse_event_ids(value: str | None) -> list[str] | None:
    if not value:
        return None
    ids = [item.strip() for item in value.split(",") if item.strip()]
    return ids or None


def filter_verified_rows(
    verified_rows: list[dict[str, Any]],
    event_ids: list[str] | None = None,
    max_events: int | None = None,
    include_supported_only: bool = False,
    include_weak: bool = False,
    include_issues: bool = False,
    sample_strategy: str = "input",
) -> list[dict[str, Any]]:
    selected_event_ids = list(dict.fromkeys(row.get("event_id") for row in verified_rows if row.get("event_id")))
    if event_ids:
        allowed = set(event_ids)
        selected_event_ids = [event_id for event_id in selected_event_ids if event_id in allowed]
    if max_events is not None:
        if sample_strategy == "balanced":
            selected_event_ids = selected_event_ids[:max_events]
        else:
            selected_event_ids = selected_event_ids[:max_events]
    allowed_events = set(selected_event_ids)

    rows: list[dict[str, Any]] = []
    for row in verified_rows:
        if row.get("event_id") not in allowed_events:
            continue
        label = normalize_label(row.get("verification_label"))
        flags = [flag for flag in split_cell(row.get("issue_flags")) if flag != "no_issue"]
        if include_supported_only and label != "supported":
            continue
        if not include_weak and label == "partially_supported" and include_supported_only:
            continue
        if not include_issues and include_supported_only and flags:
            continue
        rows.append(row)
    return rows


def normalize_label(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in SUPPORT_LABELS else "unsupported"


def build_review_rows(
    verified_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    event_ids: list[str] | None = None,
    max_events: int | None = None,
    include_supported_only: bool = False,
    include_weak: bool = False,
    include_issues: bool = False,
    sample_strategy: str = "input",
) -> list[dict[str, Any]]:
    event_index = load_event_index(events)
    evidence_index = load_evidence_index(evidence_rows)
    chain_index = load_chain_index(chains)
    selected = filter_verified_rows(
        verified_rows,
        event_ids=event_ids,
        max_events=max_events,
        include_supported_only=include_supported_only,
        include_weak=include_weak,
        include_issues=include_issues,
        sample_strategy=sample_strategy,
    )
    rows = []
    for candidate in selected:
        event_id = str(candidate.get("event_id", ""))
        label = normalize_label(candidate.get("verification_label"))
        issue_flags = split_cell(candidate.get("issue_flags"))
        evidence_ids = split_cell(candidate.get("evidence_ids"))
        evidence_texts = [make_excerpt(evidence_index.get(eid, {}).get("text", ""), 260) for eid in evidence_ids]
        chain = chain_index.get(event_id, {})
        notes = ""
        if label == "partially_supported":
            notes = f"verification_rationale: {candidate.get('verification_rationale', '')}; issue_flags: {';'.join(issue_flags)}"
        elif label == "unsupported":
            notes = "建议人工重点审核，默认不得进入 gold，除非人工修正后标记 revise/approved。"
        rows.append(
            {
                "event_id": event_id,
                "event_name": event_index.get(event_id, {}).get("event_name", ""),
                "tuple_id": candidate.get("tuple_id", ""),
                "candidate_stakeholder": candidate.get("stakeholder", ""),
                "candidate_opinion": candidate.get("opinion", ""),
                "candidate_sentiment": candidate.get("sentiment", ""),
                "candidate_rationale": candidate.get("rationale", ""),
                "candidate_evidence_ids": evidence_ids,
                "candidate_event_chain_stage": candidate.get("event_chain_stage", "unknown"),
                "candidate_confidence": candidate.get("candidate_confidence", candidate.get("confidence", "")),
                "verification_label": label,
                "verification_score": candidate.get("verification_score", ""),
                "verification_rationale": candidate.get("verification_rationale", ""),
                "issue_flags": issue_flags,
                "evidence_quotes": split_cell(candidate.get("evidence_quotes")),
                "evidence_texts": evidence_texts,
                "chain_confidence": chain.get("chain_confidence", ""),
                "missing_stages": split_cell(chain.get("missing_stages")),
                "human_decision": "need_review",
                "gold_stakeholder": candidate.get("stakeholder", ""),
                "gold_opinion": candidate.get("opinion", ""),
                "gold_sentiment": candidate.get("sentiment", ""),
                "gold_rationale": candidate.get("rationale", ""),
                "gold_evidence_ids": evidence_ids,
                "gold_event_chain_stage": candidate.get("event_chain_stage", "unknown"),
                "gold_support_label": label,
                "gold_event_chain_order": "",
                "gold_notes": notes,
                "annotator_id": "",
                "review_status": "unreviewed",
                "adjudication_status": "",
            }
        )
    return rows


def make_excerpt(text: Any, limit: int = 300) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned[:limit] + ("..." if len(cleaned) > limit else "")


def build_new_tuple_template(events: list[dict[str, Any]], event_ids: list[str] | None = None) -> list[dict[str, Any]]:
    allowed = set(event_ids or [])
    rows = []
    for event in events:
        event_id = str(event.get("event_id", ""))
        if allowed and event_id not in allowed:
            continue
        rows.append(
            {
                "event_id": event_id,
                "event_name": event.get("event_name", ""),
                "gold_stakeholder": "",
                "gold_opinion": "",
                "gold_sentiment": "",
                "gold_rationale": "",
                "gold_evidence_ids": "",
                "gold_event_chain_stage": "unknown",
                "gold_support_label": "",
                "gold_event_chain_order": "",
                "gold_notes": "",
                "annotator_id": "",
                "review_status": "unreviewed",
                "adjudication_status": "",
            }
        )
    return rows


def build_evidence_inventory(
    events: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    event_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    event_index = load_event_index(events)
    allowed = set(event_ids or [])
    stage_by_evidence: dict[str, str] = {}
    for chain in chains:
        for stage in chain.get("stages", []) or []:
            for item in stage.get("evidence", []) or []:
                evidence_id = str(item.get("evidence_id", ""))
                if evidence_id:
                    stage_by_evidence[evidence_id] = str(item.get("stage") or stage.get("stage") or "unknown")
    rows = []
    for evidence in evidence_rows:
        event_id = str(evidence.get("event_id", ""))
        if allowed and event_id not in allowed:
            continue
        rows.append(
            {
                "event_id": event_id,
                "event_name": event_index.get(event_id, {}).get("event_name", ""),
                "evidence_id": evidence.get("evidence_id", ""),
                "source": evidence.get("source", ""),
                "domain": evidence.get("domain", evidence.get("platform", "")),
                "url": evidence.get("url", ""),
                "title": evidence.get("title", ""),
                "text_excerpt": make_excerpt(evidence.get("text", ""), 500),
                "candidate_stage": stage_by_evidence.get(str(evidence.get("evidence_id", "")), evidence.get("temporal_stage", "")),
                "source_type": evidence.get("original_source", evidence.get("source", "")),
                "quality_score": evidence.get("quality_score", ""),
            }
        )
    return rows


def build_event_review_packet(
    review_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    chains: list[dict[str, Any]],
) -> str:
    event_index = load_event_index(events)
    chain_index = load_chain_index(chains)
    rows_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in review_rows:
        rows_by_event[row["event_id"]].append(row)

    parts = [REVIEW_INSTRUCTIONS, ""]
    for event_id in sorted(rows_by_event):
        event = event_index.get(event_id, {})
        chain = chain_index.get(event_id, {})
        parts.append(f"## {event_id} {event.get('event_name', '')}")
        parts.append(f"- event_id: {event_id}")
        parts.append(f"- event_name: {event.get('event_name', '')}")
        parts.append(f"- event_description: {event.get('event_description', '')}")
        parts.append(f"- chain_confidence: {chain.get('chain_confidence', '')}")
        parts.append(f"- missing_stages: {stringify_cell(chain.get('missing_stages', []))}")
        parts.append("")
        for row in rows_by_event[event_id]:
            parts.append(f"### Tuple {row.get('tuple_id', '')}")
            parts.append(f"- candidate: {row.get('candidate_stakeholder', '')} | {row.get('candidate_opinion', '')} | {row.get('candidate_sentiment', '')}")
            parts.append(f"- rationale: {row.get('candidate_rationale', '')}")
            parts.append(f"- stage: {row.get('candidate_event_chain_stage', '')}")
            parts.append(f"- evidence_ids: {stringify_cell(row.get('candidate_evidence_ids', ''))}")
            parts.append(f"- evidence_quotes: {stringify_cell(row.get('evidence_quotes', ''))}")
            parts.append(f"- verifier: {row.get('verification_label', '')} ({row.get('verification_score', '')}) {row.get('verification_rationale', '')}")
            parts.append(f"- issue_flags: {stringify_cell(row.get('issue_flags', ''))}")
            parts.append("- human_review: set human_decision/review_status in the CSV review sheet.")
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def build_gold_review_outputs(
    events_path: str | Path,
    evidence_path: str | Path,
    verified_path: str | Path,
    chains_path: str | Path,
    annotation_sheet_path: str | Path,
    output_dir: str | Path,
    event_ids: list[str] | None = None,
    max_events: int | None = None,
    include_supported_only: bool = False,
    include_weak: bool = False,
    include_issues: bool = False,
    sample_strategy: str = "input",
    use_llm_prelabel: bool = False,
    dry_run: bool = False,
    llm_prelabeler: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    events = read_jsonl(events_path)
    evidence = read_jsonl(evidence_path)
    verified = read_jsonl(verified_path)
    chains = read_jsonl(chains_path)
    _ = annotation_sheet_path  # Kept as an explicit input contract; never modified.

    review_rows = build_review_rows(
        verified,
        events,
        evidence,
        chains,
        event_ids=event_ids,
        max_events=max_events,
        include_supported_only=include_supported_only,
        include_weak=include_weak,
        include_issues=include_issues,
        sample_strategy=sample_strategy,
    )
    new_rows = build_new_tuple_template(events, event_ids=event_ids)
    inventory_rows = build_evidence_inventory(events, evidence, chains, event_ids=event_ids)
    packet = build_event_review_packet(review_rows, events, chains)

    output_dir = Path(output_dir)
    output_files = {
        "tuple_review_sheet": str(output_dir / "gold_tuple_review_sheet.csv"),
        "event_review_packet": str(output_dir / "event_review_packet.md"),
        "new_tuple_template": str(output_dir / "new_tuple_template.csv"),
        "evidence_inventory": str(output_dir / "evidence_inventory_for_review.csv"),
        "summary": str(output_dir / "gold_annotation_summary.json"),
    }
    if use_llm_prelabel:
        output_files["llm_prelabels"] = str(output_dir / "llm_prelabels.jsonl")

    label_counts = Counter(row.get("verification_label") for row in review_rows)
    issue_rows = sum(1 for row in review_rows if any(flag != "no_issue" for flag in split_cell(row.get("issue_flags"))))
    summary = {
        "num_events": len(set(row["event_id"] for row in review_rows)),
        "num_verified_tuples_loaded": len(verified),
        "num_review_rows": len(review_rows),
        "num_supported_prefilled": label_counts.get("supported", 0),
        "num_partially_supported_prefilled": label_counts.get("partially_supported", 0),
        "num_unsupported_prefilled": label_counts.get("unsupported", 0),
        "num_issue_rows": issue_rows,
        "output_files": output_files,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        summary["dry_run"] = True
        return summary

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(output_files["tuple_review_sheet"], review_rows, TUPLE_REVIEW_FIELDS)
    Path(output_files["event_review_packet"]).write_text(packet, encoding="utf-8")
    write_csv_rows(output_files["new_tuple_template"], new_rows, NEW_TUPLE_FIELDS)
    write_csv_rows(output_files["evidence_inventory"], inventory_rows, EVIDENCE_INVENTORY_FIELDS)

    if use_llm_prelabel:
        prelabels = build_llm_prelabels(events, evidence, review_rows, llm_prelabeler)
        write_jsonl(output_files["llm_prelabels"], prelabels)

    Path(output_files["summary"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_llm_prelabels(
    events: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    llm_prelabeler: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    if llm_prelabeler is None:
        return []
    event_index = load_event_index(events)
    tuple_evidence_ids = {eid for row in review_rows for eid in split_cell(row.get("candidate_evidence_ids"))}
    rows = []
    for evidence in evidence_rows:
        evidence_id = str(evidence.get("evidence_id", ""))
        if evidence_id in tuple_evidence_ids:
            continue
        event = event_index.get(str(evidence.get("event_id", "")), {})
        for item in llm_prelabeler(event, evidence):
            rows.append(
                {
                    "event_id": evidence.get("event_id", ""),
                    "evidence_id": evidence_id,
                    "prelabel_stakeholder": item.get("stakeholder", ""),
                    "prelabel_opinion": item.get("opinion", ""),
                    "prelabel_sentiment": item.get("sentiment", ""),
                    "prelabel_rationale": item.get("rationale", ""),
                    "prelabel_support_label": item.get("support_label", ""),
                    "prelabel_event_chain_stage": item.get("event_chain_stage", ""),
                    "prelabel_confidence": item.get("confidence", ""),
                    "raw_response_id": item.get("raw_response_id", ""),
                    "prelabel_status": item.get("prelabel_status", "suggested"),
                }
            )
    return rows


def row_can_enter_gold(row: dict[str, Any], evidence_ids: set[str], is_new: bool = False) -> tuple[bool, str]:
    review_status = str(row.get("review_status", "")).strip()
    decision = str(row.get("human_decision", "")).strip()
    if review_status not in REVIEWED_STATUSES:
        return False, "review_status_not_reviewed"
    if is_new:
        if decision not in NEW_TUPLE_DECISIONS:
            return False, "human_decision_not_added"
    elif decision not in ACCEPT_DECISIONS:
        return False, "human_decision_not_accept_or_revise"
    if not str(row.get("gold_stakeholder", "")).strip():
        return False, "missing_gold_stakeholder"
    if not str(row.get("gold_opinion", "")).strip():
        return False, "missing_gold_opinion"
    sentiment = str(row.get("gold_sentiment", "")).strip()
    if sentiment not in SENTIMENTS:
        return False, "invalid_gold_sentiment"
    if not str(row.get("gold_rationale", "")).strip():
        return False, "missing_gold_rationale"
    ids = split_cell(row.get("gold_evidence_ids"))
    if not ids:
        return False, "missing_gold_evidence_ids"
    missing = [eid for eid in ids if eid not in evidence_ids]
    if missing:
        return False, f"missing_evidence_id:{';'.join(missing)}"
    if str(row.get("gold_support_label", "")).strip() not in SUPPORT_LABELS:
        return False, "invalid_gold_support_label"
    return True, ""


def convert_review_sheets_to_gold(
    review_sheet: str | Path,
    new_tuples: str | Path,
    evidence_path: str | Path,
    events_path: str | Path,
    output_dir: str | Path,
    write_to_dataset_gold: bool = False,
    dataset_dir: str | Path = "data/pubevent_soa_lite",
) -> dict[str, Any]:
    evidence_ids = set(load_evidence_index(read_jsonl(evidence_path)))
    event_ids = set(load_event_index(read_jsonl(events_path)))
    review_rows = read_csv_rows(review_sheet)
    new_rows = read_csv_rows(new_tuples)

    gold_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    counters: dict[str, int] = defaultdict(int)

    for row in review_rows:
        ok, reason = row_can_enter_gold(row, evidence_ids, is_new=False)
        if not ok:
            rejected_rows.append({**row, "exclusion_reason": reason})
            counters[reason] += 1
            continue
        if row.get("event_id") not in event_ids:
            rejected_rows.append({**row, "exclusion_reason": "unknown_event_id"})
            counters["unknown_event_id"] += 1
            continue
        gold_rows.append(make_gold_tuple(row, source_candidate_tuple_id=row.get("tuple_id", ""), human_decision=row.get("human_decision", "")))

    for row in new_rows:
        if not any(str(row.get(field, "")).strip() for field in NEW_TUPLE_FIELDS):
            continue
        ok, reason = row_can_enter_gold(row, evidence_ids, is_new=True)
        if not ok:
            rejected_rows.append({**row, "exclusion_reason": reason})
            counters[reason] += 1
            continue
        if row.get("event_id") not in event_ids:
            rejected_rows.append({**row, "exclusion_reason": "unknown_event_id"})
            counters["unknown_event_id"] += 1
            continue
        gold_rows.append(make_gold_tuple(row, source_candidate_tuple_id="", human_decision="added"))

    assign_gold_tuple_ids(gold_rows)
    chains = build_gold_event_chains(gold_rows)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gold_tuples_path = output_dir / "gold_tuples.jsonl"
    gold_chains_path = output_dir / "gold_event_chains.jsonl"
    rejected_path = output_dir / "rejected_or_unreviewed_rows.csv"
    summary_path = output_dir / "gold_export_summary.json"
    write_jsonl(gold_tuples_path, gold_rows)
    write_jsonl(gold_chains_path, chains)
    rejected_fields = sorted({key for row in rejected_rows for key in row} | {"exclusion_reason"})
    write_csv_rows(rejected_path, rejected_rows, rejected_fields)

    copied_to_dataset = False
    if write_to_dataset_gold:
        dataset_dir = Path(dataset_dir)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gold_tuples_path, dataset_dir / "gold_tuples.jsonl")
        shutil.copyfile(gold_chains_path, dataset_dir / "gold_event_chains.jsonl")
        copied_to_dataset = True

    summary = {
        "num_review_rows": len(review_rows),
        "num_new_tuple_rows": len(new_rows),
        "num_gold_tuples": len(gold_rows),
        "num_gold_event_chains": len(chains),
        "num_rejected_or_unreviewed_rows": len(rejected_rows),
        "exclusion_reasons": dict(counters),
        "output_files": {
            "gold_tuples": str(gold_tuples_path),
            "gold_event_chains": str(gold_chains_path),
            "rejected_or_unreviewed_rows": str(rejected_path),
            "summary": str(summary_path),
        },
        "copied_to_dataset_gold": copied_to_dataset,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def make_gold_tuple(row: dict[str, Any], source_candidate_tuple_id: str, human_decision: str) -> dict[str, Any]:
    stage = str(row.get("gold_event_chain_stage") or "unknown").strip() or "unknown"
    if stage not in STAGES:
        stage = "unknown"
    return {
        "event_id": row.get("event_id", ""),
        "gold_tuple_id": "",
        "stakeholder": str(row.get("gold_stakeholder", "")).strip(),
        "opinion": str(row.get("gold_opinion", "")).strip(),
        "sentiment": str(row.get("gold_sentiment", "")).strip(),
        "rationale": str(row.get("gold_rationale", "")).strip(),
        "evidence_ids": split_cell(row.get("gold_evidence_ids")),
        "event_chain_stage": stage,
        "support_label": str(row.get("gold_support_label", "")).strip(),
        "source_candidate_tuple_id": source_candidate_tuple_id,
        "_gold_event_chain_order": str(row.get("gold_event_chain_order", "")).strip(),
        "annotation_provenance": {
            "source": "human_reviewed_llm_assisted",
            "human_decision": human_decision,
            "review_status": row.get("review_status", ""),
            "annotator_id": row.get("annotator_id", ""),
            "adjudication_status": row.get("adjudication_status", ""),
            "notes": row.get("gold_notes", ""),
        },
    }


def assign_gold_tuple_ids(gold_rows: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for row in sorted(gold_rows, key=lambda item: (item.get("event_id", ""), item.get("source_candidate_tuple_id", ""))):
        event_id = str(row.get("event_id", ""))
        counts[event_id] += 1
        row["gold_tuple_id"] = f"G_{event_id}_{counts[event_id]:03d}"


def parse_order(value: Any, stage: str) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return STAGE_ORDER.get(stage, 99)


def build_gold_event_chains(gold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in gold_rows:
        grouped[(str(row.get("event_id", "")), str(row.get("event_chain_stage", "unknown")))].append(row)

    chains = []
    chain_counts: dict[str, int] = defaultdict(int)
    for (event_id, stage), rows in sorted(grouped.items(), key=lambda item: (item[0][0], parse_order(item[1][0].get("_gold_event_chain_order"), item[0][1]), item[0][1])):
        chain_counts[event_id] += 1
        evidence_ids = unique(item for row in rows for item in row.get("evidence_ids", []))
        summary = build_chain_summary(rows)
        chains.append(
            {
                "event_id": event_id,
                "gold_chain_id": f"GC_{event_id}_{chain_counts[event_id]:03d}",
                "stage": stage,
                "order": parse_order(rows[0].get("_gold_event_chain_order"), stage),
                "evidence_ids": evidence_ids,
                "summary": summary,
                "source_gold_tuple_ids": [row.get("gold_tuple_id", "") for row in rows],
                "annotation_provenance": {"source": "human_reviewed_llm_assisted"},
            }
        )
    for row in gold_rows:
        row.pop("_gold_event_chain_order", None)
    return chains


def unique(values: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def build_chain_summary(rows: list[dict[str, Any]]) -> str:
    snippets = []
    for row in rows[:4]:
        opinion = str(row.get("opinion", "")).strip()
        rationale = str(row.get("rationale", "")).strip()
        if opinion and rationale:
            snippets.append(f"{opinion}（{rationale}）")
        elif opinion:
            snippets.append(opinion)
    return "；".join(snippets)[:500]


def validate_gold_dataset(
    gold_tuples_path: str | Path,
    gold_event_chains_path: str | Path,
    evidence_path: str | Path,
    events_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    hard_errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    tuple_path = Path(gold_tuples_path)
    chain_path = Path(gold_event_chains_path)

    if not tuple_path.exists() or tuple_path.stat().st_size == 0:
        hard_errors.append({"check": "gold_tuples_nonempty", "message": "gold_tuples file missing or empty"})
        gold_rows: list[dict[str, Any]] = []
    else:
        gold_rows = read_jsonl(tuple_path)
    if not chain_path.exists() or chain_path.stat().st_size == 0:
        hard_errors.append({"check": "gold_event_chains_nonempty", "message": "gold_event_chains file missing or empty"})
        chain_rows: list[dict[str, Any]] = []
    else:
        chain_rows = read_jsonl(chain_path)

    event_ids = set(load_event_index(read_jsonl(events_path)))
    evidence_ids = set(load_evidence_index(read_jsonl(evidence_path)))
    tuple_counts = Counter()
    sentiment_counts = Counter()
    support_counts = Counter()
    stage_counts = Counter()

    for idx, row in enumerate(gold_rows, start=1):
        prefix = f"gold_tuple:{idx}:{row.get('gold_tuple_id', '')}"
        event_id = row.get("event_id")
        tuple_counts[event_id] += 1
        sentiment_counts[row.get("sentiment")] += 1
        support_counts[row.get("support_label")] += 1
        stage_counts[row.get("event_chain_stage")] += 1
        if event_id not in event_ids:
            hard_errors.append({"check": "event_id_exists", "row": prefix, "message": str(event_id)})
        for evidence_id in row.get("evidence_ids", []) or []:
            if evidence_id not in evidence_ids:
                hard_errors.append({"check": "evidence_id_exists", "row": prefix, "message": str(evidence_id)})
        if row.get("sentiment") not in SENTIMENTS:
            hard_errors.append({"check": "sentiment_valid", "row": prefix, "message": str(row.get("sentiment"))})
        if row.get("support_label") not in SUPPORT_LABELS:
            hard_errors.append({"check": "support_label_valid", "row": prefix, "message": str(row.get("support_label"))})
        for field in ("stakeholder", "opinion", "rationale"):
            if not str(row.get(field, "")).strip():
                hard_errors.append({"check": f"{field}_nonempty", "row": prefix, "message": "empty"})
        provenance = row.get("annotation_provenance") or {}
        if not provenance.get("source"):
            hard_errors.append({"check": "annotation_provenance_source", "row": prefix, "message": "missing"})
        if provenance.get("review_status") not in REVIEWED_STATUSES:
            hard_errors.append({"check": "review_status_reviewed", "row": prefix, "message": str(provenance.get("review_status"))})
        if provenance.get("human_decision") in {"reject", "rejected", "need_review", "unclear"}:
            hard_errors.append({"check": "human_decision_allowed", "row": prefix, "message": str(provenance.get("human_decision"))})

    for event_id in sorted(event_ids):
        if tuple_counts[event_id] == 0:
            warnings.append({"check": "event_has_gold_tuple", "event_id": event_id, "message": "no gold tuple"})

    report = {
        "hard_error_count": len(hard_errors),
        "warning_count": len(warnings),
        "hard_errors": hard_errors,
        "warnings": warnings,
        "num_gold_tuples": len(gold_rows),
        "num_gold_event_chains": len(chain_rows),
        "event_gold_tuple_counts": dict(tuple_counts),
        "sentiment_distribution": dict(sentiment_counts),
        "support_label_distribution": dict(support_counts),
        "event_chain_stage_distribution": dict(stage_counts),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "gold_validation_report.json"
        csv_path = output_dir / "gold_validation_report.csv"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        flat_rows = [dict(item, severity="hard_error") for item in hard_errors] + [dict(item, severity="warning") for item in warnings]
        fields = sorted({key for row in flat_rows for key in row} | {"severity", "check", "message"})
        write_csv_rows(csv_path, flat_rows, fields)
    return report


def inspect_gold_samples(
    gold_tuples_path: str | Path,
    evidence_path: str | Path | None = None,
    event_id: str | None = None,
    limit: int = 20,
    show_evidence: bool = False,
) -> str:
    rows = read_jsonl(gold_tuples_path)
    if event_id:
        rows = [row for row in rows if row.get("event_id") == event_id]
    rows = rows[:limit]
    evidence_index = load_evidence_index(read_jsonl(evidence_path)) if show_evidence and evidence_path else {}
    parts = []
    for row in rows:
        parts.append(f"{row.get('gold_tuple_id')} {row.get('event_id')} {row.get('event_chain_stage')} {row.get('sentiment')} {row.get('support_label')}")
        parts.append(f"  stakeholder: {row.get('stakeholder')}")
        parts.append(f"  opinion: {row.get('opinion')}")
        parts.append(f"  rationale: {row.get('rationale')}")
        parts.append(f"  evidence_ids: {', '.join(row.get('evidence_ids', []))}")
        if show_evidence:
            for eid in row.get("evidence_ids", []):
                parts.append(f"    {eid}: {make_excerpt(evidence_index.get(eid, {}).get('text', ''), 240)}")
    return "\n".join(parts)

