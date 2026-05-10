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


# Gold annotation pipeline v1 -------------------------------------------------
#
# The definitions below intentionally override the earlier compatibility helpers
# while keeping their public names. Existing tests and scripts still import the
# same symbols, but the default workflow now matches the formal PubEvent-SOA data
# flow based on data/pubevent_soa_lite/evidence.jsonl.

SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}
SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "insufficient_evidence"}
HUMAN_DECISIONS = {"accept", "edit", "reject", "add_new", "merge"}
EXPORT_DECISIONS = {"accept", "edit", "add_new", "merge", "revise", "revised", "approved", "added", "add_missing"}
FINAL_STATUSES = {"", "final", "adjudicated", "approved", "reviewed"}

TUPLE_REVIEW_FIELDS = [
    "event_id",
    "candidate_id",
    "source_type",
    "stakeholder",
    "opinion",
    "sentiment",
    "rationale",
    "evidence_ids",
    "support_label",
    "human_decision",
    "gold_stakeholder",
    "gold_opinion",
    "gold_sentiment",
    "gold_rationale",
    "gold_evidence_ids",
    "gold_support_label",
    "edit_reason",
    "reviewer_id",
    "adjudication_status",
    "notes",
    # Backward-compatible fields used by older review tooling/tests.
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
    "gold_event_chain_stage",
    "gold_event_chain_order",
    "gold_notes",
    "annotator_id",
    "review_status",
]

CHAIN_REVIEW_FIELDS = [
    "event_id",
    "candidate_chain_id",
    "source_type",
    "event_chain",
    "evidence_ids",
    "human_decision",
    "gold_event_chain",
    "gold_evidence_ids",
    "edit_reason",
    "reviewer_id",
    "adjudication_status",
    "notes",
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
    "human_decision",
]


def normalize_label(value: Any) -> str:
    text = str(value or "").strip()
    if text in SUPPORT_LABELS:
        return text
    if text == "irrelevant":
        return "insufficient_evidence"
    return "insufficient_evidence"


def normalize_sentiment(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in SENTIMENTS else "unknown"


def parse_json_or_cell(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return split_cell(text)


def unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def load_optional_jsonl(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    return read_jsonl(path)


def event_name(event: dict[str, Any]) -> str:
    return str(event.get("event_name") or event.get("event_description") or "")


def candidate_id(row: dict[str, Any], index: int) -> str:
    return str(
        row.get("candidate_id")
        or row.get("tuple_id")
        or row.get("gold_tuple_id")
        or f"{row.get('event_id', 'event')}_candidate_{index:04d}"
    )


def chain_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("candidate_chain_id") or row.get("chain_id") or row.get("gold_chain_id") or f"chain_{index:04d}")


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
    _ = (include_weak, include_issues, sample_strategy)
    event_index = load_event_index(events)
    evidence_index = load_evidence_index(evidence_rows)
    chain_index = load_chain_index(chains)
    allowed = set(event_ids or [])
    if max_events is not None and not allowed:
        allowed = {str(event.get("event_id")) for event in events[:max_events] if event.get("event_id")}

    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(verified_rows, start=1):
        event_id = str(candidate.get("event_id") or "")
        if allowed and event_id not in allowed:
            continue
        label = normalize_label(candidate.get("support_label") or candidate.get("verification_label"))
        if include_supported_only and label != "supported":
            continue
        ids = unique(parse_json_or_cell(candidate.get("evidence_ids") or candidate.get("candidate_evidence_ids")))
        cid = candidate_id(candidate, index)
        stakeholder = str(candidate.get("stakeholder") or candidate.get("gold_stakeholder") or "")
        opinion = str(candidate.get("opinion") or candidate.get("gold_opinion") or "")
        sentiment = normalize_sentiment(candidate.get("sentiment") or candidate.get("gold_sentiment"))
        rationale = str(candidate.get("rationale") or candidate.get("gold_rationale") or "")
        evidence_texts = [make_excerpt(evidence_index.get(eid, {}).get("text", ""), 260) for eid in ids]
        chain = chain_index.get(event_id, {})
        stage = str(candidate.get("event_chain_stage") or candidate.get("gold_event_chain_stage") or "unknown")
        gold_notes = ""
        if label == "partially_supported":
            gold_notes = f"verification_rationale: {candidate.get('verification_rationale', '')}; issue_flags: {';'.join(parse_json_or_cell(candidate.get('issue_flags')))}"
        elif label in {"unsupported", "insufficient_evidence"}:
            gold_notes = "requires human review before entering gold"
        row = {
            "event_id": event_id,
            "candidate_id": cid,
            "source_type": str(candidate.get("source_type") or candidate.get("source") or "system_candidate"),
            "stakeholder": stakeholder,
            "opinion": opinion,
            "sentiment": sentiment,
            "rationale": rationale,
            "evidence_ids": ids,
            "support_label": label,
            "human_decision": "need_review",
            "gold_stakeholder": stakeholder,
            "gold_opinion": opinion,
            "gold_sentiment": sentiment,
            "gold_rationale": rationale,
            "gold_evidence_ids": ids,
            "gold_support_label": label,
            "edit_reason": "",
            "reviewer_id": "",
            "adjudication_status": "",
            "notes": "",
            "event_name": event_name(event_index.get(event_id, {})),
            "tuple_id": cid,
            "candidate_stakeholder": stakeholder,
            "candidate_opinion": opinion,
            "candidate_sentiment": sentiment,
            "candidate_rationale": rationale,
            "candidate_evidence_ids": ids,
            "candidate_event_chain_stage": stage,
            "candidate_confidence": candidate.get("candidate_confidence", candidate.get("confidence", "")),
            "verification_label": label,
            "verification_score": candidate.get("verification_score", ""),
            "verification_rationale": candidate.get("verification_rationale", ""),
            "issue_flags": parse_json_or_cell(candidate.get("issue_flags")),
            "evidence_quotes": parse_json_or_cell(candidate.get("evidence_quotes")),
            "evidence_texts": evidence_texts,
            "chain_confidence": chain.get("chain_confidence", ""),
            "missing_stages": parse_json_or_cell(chain.get("missing_stages")),
            "gold_event_chain_stage": stage,
            "gold_event_chain_order": "",
            "gold_notes": gold_notes,
            "annotator_id": "",
            "review_status": "unreviewed",
        }
        if not verified_rows:
            row["source_type"] = "blank_template"
        rows.append(row)
    return rows


def blank_tuple_rows_for_events(events: list[dict[str, Any]], event_ids: list[str] | None = None) -> list[dict[str, Any]]:
    allowed = set(event_ids or [])
    rows: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        if allowed and event_id not in allowed:
            continue
        rows.append(
            {
                "event_id": event_id,
                "candidate_id": "",
                "source_type": "blank_template",
                "stakeholder": "",
                "opinion": "",
                "sentiment": "",
                "rationale": "",
                "evidence_ids": "",
                "support_label": "",
                "human_decision": "",
                "gold_stakeholder": "",
                "gold_opinion": "",
                "gold_sentiment": "",
                "gold_rationale": "",
                "gold_evidence_ids": "",
                "gold_support_label": "",
                "edit_reason": "",
                "reviewer_id": "",
                "adjudication_status": "",
                "notes": "",
                "event_name": event_name(event),
                "tuple_id": "",
                "review_status": "unreviewed",
            }
        )
    return rows


def build_chain_review_rows(
    events: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    event_ids: list[str] | None = None,
    max_events: int | None = None,
) -> list[dict[str, Any]]:
    allowed = set(event_ids or [])
    if max_events is not None and not allowed:
        allowed = {str(event.get("event_id")) for event in events[:max_events] if event.get("event_id")}
    rows: list[dict[str, Any]] = []
    for index, chain in enumerate(chains, start=1):
        event_id = str(chain.get("event_id") or "")
        if allowed and event_id not in allowed:
            continue
        nodes = chain.get("event_chain") or chain.get("chain_nodes") or chain.get("nodes") or []
        if not nodes and isinstance(chain.get("stages"), list):
            nodes = [str(stage.get("stage") or "") for stage in chain["stages"] if stage.get("stage")]
        evidence_ids = unique(
            item
            for stage in chain.get("stages", []) or []
            for evidence in stage.get("evidence", []) or []
            for item in [str(evidence.get("evidence_id") or "")]
        )
        evidence_ids = evidence_ids or unique(parse_json_or_cell(chain.get("evidence_ids")))
        rows.append(
            {
                "event_id": event_id,
                "candidate_chain_id": chain_id(chain, index),
                "source_type": str(chain.get("source_type") or "system_candidate"),
                "event_chain": nodes,
                "evidence_ids": evidence_ids,
                "human_decision": "",
                "gold_event_chain": nodes,
                "gold_evidence_ids": evidence_ids,
                "edit_reason": "",
                "reviewer_id": "",
                "adjudication_status": "",
                "notes": "",
            }
        )
    if not rows:
        for event in events:
            event_id = str(event.get("event_id") or "")
            if allowed and event_id not in allowed:
                continue
            rows.append(
                {
                    "event_id": event_id,
                    "candidate_chain_id": "",
                    "source_type": "blank_template",
                    "event_chain": "",
                    "evidence_ids": "",
                    "human_decision": "",
                    "gold_event_chain": "",
                    "gold_evidence_ids": "",
                    "edit_reason": "",
                    "reviewer_id": "",
                    "adjudication_status": "",
                    "notes": "",
                }
            )
    return rows


def build_gold_review_outputs(
    events_path: str | Path,
    evidence_path: str | Path,
    verified_path: str | Path | None,
    chains_path: str | Path | None,
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
    _ = (annotation_sheet_path, use_llm_prelabel, llm_prelabeler)
    events = read_jsonl(events_path)
    evidence = read_jsonl(evidence_path)
    verified = load_optional_jsonl(verified_path)
    chains = load_optional_jsonl(chains_path)
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
    if not review_rows:
        review_rows = blank_tuple_rows_for_events(events, event_ids=event_ids)
    chain_rows = build_chain_review_rows(events, chains, event_ids=event_ids, max_events=max_events)

    output_dir = Path(output_dir)
    output_files = {
        "tuple_review_sheet": str(output_dir / "gold_tuple_review_sheet.csv"),
        "chain_review_sheet": str(output_dir / "gold_chain_review_sheet.csv"),
        "summary": str(output_dir / "gold_review_summary.json"),
    }
    summary = {
        "num_events": len({str(row.get("event_id")) for row in events if row.get("event_id")}),
        "num_evidence": len(evidence),
        "num_candidate_tuples": len(verified),
        "num_candidate_chains": len(chains),
        "num_tuple_review_rows": len(review_rows),
        "num_chain_review_rows": len(chain_rows),
        "output_files": output_files,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if dry_run:
        summary["dry_run"] = True
        return summary
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(output_files["tuple_review_sheet"], review_rows, TUPLE_REVIEW_FIELDS)
    write_csv_rows(output_files["chain_review_sheet"], chain_rows, CHAIN_REVIEW_FIELDS)
    Path(output_files["summary"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def is_final_row(row: dict[str, Any]) -> bool:
    status = str(row.get("adjudication_status") or row.get("review_status") or "").strip()
    decision = str(row.get("human_decision") or "").strip()
    if decision == "reject":
        return False
    return decision in EXPORT_DECISIONS and status in FINAL_STATUSES


def row_can_enter_gold(row: dict[str, Any], evidence_ids: set[str], is_new: bool = False) -> tuple[bool, str]:
    _ = is_new
    if not is_final_row(row):
        return False, "not_final_human_decision"
    if not str(row.get("gold_stakeholder", "")).strip():
        return False, "missing_gold_stakeholder"
    if not str(row.get("gold_opinion", "")).strip():
        return False, "missing_gold_opinion"
    if normalize_sentiment(row.get("gold_sentiment")) != str(row.get("gold_sentiment", "")).strip():
        return False, "invalid_gold_sentiment"
    if not str(row.get("gold_rationale", "")).strip():
        return False, "missing_gold_rationale"
    ids = unique(parse_json_or_cell(row.get("gold_evidence_ids")))
    if not ids:
        return False, "missing_gold_evidence_ids"
    missing = [eid for eid in ids if eid not in evidence_ids]
    if missing:
        return False, f"missing_evidence_id:{';'.join(missing)}"
    if str(row.get("gold_support_label", "")).strip() not in SUPPORT_LABELS:
        return False, "invalid_gold_support_label"
    return True, ""


def make_gold_tuple(row: dict[str, Any], source_candidate_tuple_id: str, human_decision: str) -> dict[str, Any]:
    decision = str(human_decision or row.get("human_decision") or "").strip()
    return {
        "event_id": str(row.get("event_id", "")).strip(),
        "gold_tuple_id": "",
        "stakeholder": str(row.get("gold_stakeholder", "")).strip(),
        "opinion": str(row.get("gold_opinion", "")).strip(),
        "sentiment": str(row.get("gold_sentiment", "")).strip(),
        "rationale": str(row.get("gold_rationale", "")).strip(),
        "evidence_ids": unique(parse_json_or_cell(row.get("gold_evidence_ids"))),
        "event_chain_stage": str(row.get("gold_event_chain_stage") or "unknown").strip() or "unknown",
        "support_label": str(row.get("gold_support_label", "")).strip(),
        "source_candidate_tuple_id": source_candidate_tuple_id,
        "_gold_event_chain_order": str(row.get("gold_event_chain_order", "")).strip(),
        "annotation_provenance": {
            "source": "human_reviewed_llm_assisted",
            "human_decision": decision,
            "review_status": str(row.get("review_status") or row.get("adjudication_status") or "reviewed"),
            "reviewer_id": str(row.get("reviewer_id") or row.get("annotator_id") or ""),
            "annotator_id": str(row.get("annotator_id") or row.get("reviewer_id") or ""),
            "adjudication_status": str(row.get("adjudication_status") or ""),
            "notes": str(row.get("notes") or row.get("gold_notes") or ""),
            "edit_reason": str(row.get("edit_reason") or ""),
        },
    }


def tuple_dedupe_key(row: dict[str, Any]) -> tuple[str, str, str, str, tuple[str, ...]]:
    return (
        str(row.get("event_id", "")),
        str(row.get("stakeholder", "")).strip().lower(),
        str(row.get("opinion", "")).strip().lower(),
        str(row.get("sentiment", "")).strip(),
        tuple(sorted(row.get("evidence_ids", []) or [])),
    )


def assign_gold_tuple_ids(gold_rows: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for row in gold_rows:
        event_id = str(row.get("event_id", ""))
        counts[event_id] += 1
        row["gold_tuple_id"] = f"G_{event_id}_{counts[event_id]:03d}"


def convert_review_sheets_to_gold(
    review_sheet: str | Path,
    new_tuples: str | Path | None = None,
    evidence_path: str | Path = "data/pubevent_soa_lite/evidence.jsonl",
    events_path: str | Path = "data/pubevent_soa_lite/events.jsonl",
    output_dir: str | Path = "data/pubevent_soa_lite",
    write_to_dataset_gold: bool = False,
    dataset_dir: str | Path = "data/pubevent_soa_lite",
    chain_review_sheet: str | Path | None = None,
) -> dict[str, Any]:
    evidence = read_jsonl(evidence_path)
    evidence_ids = set(load_evidence_index(evidence))
    event_ids = set(load_event_index(read_jsonl(events_path)))
    review_rows = read_csv_rows(review_sheet)
    new_rows = read_csv_rows(new_tuples) if new_tuples else []
    chain_rows = read_csv_rows(chain_review_sheet) if chain_review_sheet else []

    counters: dict[str, int] = defaultdict(int)
    rejected_rows: list[dict[str, Any]] = []
    exported: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, tuple[str, ...]]] = set()

    for row in [*review_rows, *new_rows]:
        decision = str(row.get("human_decision") or "").strip()
        if decision == "reject":
            counters["rejected"] += 1
            rejected_rows.append({**row, "exclusion_reason": "rejected"})
            continue
        ok, reason = row_can_enter_gold(row, evidence_ids, is_new=row in new_rows)
        if not ok:
            counters[reason] += 1
            rejected_rows.append({**row, "exclusion_reason": reason})
            continue
        if str(row.get("event_id") or "") not in event_ids:
            counters["unknown_event_id"] += 1
            rejected_rows.append({**row, "exclusion_reason": "unknown_event_id"})
            continue
        gold = make_gold_tuple(
            row,
            source_candidate_tuple_id=str(row.get("candidate_id") or row.get("tuple_id") or ""),
            human_decision=decision,
        )
        key = tuple_dedupe_key(gold)
        if key in seen:
            counters["duplicate_tuples_dropped"] += 1
            continue
        seen.add(key)
        exported.append(gold)
        if decision in {"accept", "approved"}:
            counters["accepted"] += 1
        elif decision in {"edit", "revise", "revised"}:
            counters["edited"] += 1
        elif decision in {"add_new", "add_missing", "added"}:
            counters["added"] += 1
        elif decision == "merge":
            counters["merged"] += 1

    assign_gold_tuple_ids(exported)
    chains = convert_chain_rows(chain_rows, exported, evidence_ids, event_ids)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gold_tuples_path = output_dir / "gold_tuples.jsonl"
    gold_chains_path = output_dir / "gold_event_chains.jsonl"
    report_path = output_dir / "gold_conversion_report.json"
    rejected_path = output_dir / "annotation" / "gold_rejected_or_unreviewed_rows.csv"
    write_jsonl(gold_tuples_path, exported)
    write_jsonl(gold_chains_path, chains)
    if rejected_rows:
        write_csv_rows(rejected_path, rejected_rows, sorted({key for row in rejected_rows for key in row}))

    if write_to_dataset_gold and Path(dataset_dir) != output_dir:
        dataset_dir = Path(dataset_dir)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gold_tuples_path, dataset_dir / "gold_tuples.jsonl")
        shutil.copyfile(gold_chains_path, dataset_dir / "gold_event_chains.jsonl")

    report = {
        "accepted": counters.get("accepted", 0),
        "edited": counters.get("edited", 0),
        "added": counters.get("added", 0),
        "rejected": counters.get("rejected", 0),
        "merged": counters.get("merged", 0),
        "exported_gold_tuples": len(exported),
        "exported_gold_event_chains": len(chains),
        "exclusion_reasons": dict(counters),
        "output_files": {
            "gold_tuples": str(gold_tuples_path),
            "gold_event_chains": str(gold_chains_path),
            "conversion_report": str(report_path),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def convert_chain_rows(
    chain_rows: list[dict[str, Any]],
    gold_tuples: list[dict[str, Any]],
    evidence_ids: set[str],
    event_ids: set[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for row in chain_rows:
        decision = str(row.get("human_decision") or "").strip()
        if decision not in EXPORT_DECISIONS:
            continue
        event_id = str(row.get("event_id") or "")
        if event_id not in event_ids:
            continue
        ids = unique(parse_json_or_cell(row.get("gold_evidence_ids")))
        if not ids or any(eid not in evidence_ids for eid in ids):
            continue
        nodes = parse_json_or_cell(row.get("gold_event_chain"))
        if not nodes:
            continue
        counts[event_id] += 1
        output.append(
            {
                "event_id": event_id,
                "gold_chain_id": f"GC_{event_id}_{counts[event_id]:03d}",
                "event_chain": nodes,
                "evidence_ids": ids,
                "annotation_provenance": {
                    "source": "human_reviewed_llm_assisted",
                    "human_decision": decision,
                    "reviewer_id": str(row.get("reviewer_id") or ""),
                    "adjudication_status": str(row.get("adjudication_status") or ""),
                    "notes": str(row.get("notes") or ""),
                },
            }
        )
    if output:
        return output
    return build_gold_event_chains(gold_tuples)


def build_gold_event_chains(gold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in gold_rows:
        grouped[(str(row.get("event_id", "")), str(row.get("event_chain_stage", "unknown")))].append(row)

    chains: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for (event_id, stage), rows in sorted(grouped.items(), key=lambda item: (item[0][0], parse_order(item[1][0].get("_gold_event_chain_order"), item[0][1]), item[0][1])):
        counts[event_id] += 1
        evidence_ids = unique(eid for row in rows for eid in row.get("evidence_ids", []) or [])
        nodes = [f"{stage}: {row.get('stakeholder', '')} - {row.get('opinion', '')}" for row in rows]
        chains.append(
            {
                "event_id": event_id,
                "gold_chain_id": f"GC_{event_id}_{counts[event_id]:03d}",
                "event_chain": nodes,
                "chain_nodes": nodes,
                "stage": stage,
                "order": parse_order(rows[0].get("_gold_event_chain_order"), stage),
                "evidence_ids": evidence_ids,
                "summary": build_chain_summary(rows),
                "source_gold_tuple_ids": [row.get("gold_tuple_id", "") for row in rows],
                "annotation_provenance": {"source": "human_reviewed_llm_assisted"},
            }
        )
    for row in gold_rows:
        row.pop("_gold_event_chain_order", None)
    return chains


def build_chain_summary(rows: list[dict[str, Any]]) -> str:
    snippets = []
    for row in rows[:4]:
        opinion = str(row.get("opinion", "")).strip()
        rationale = str(row.get("rationale", "")).strip()
        if opinion and rationale:
            snippets.append(f"{opinion} ({rationale})")
        elif opinion:
            snippets.append(opinion)
    return "; ".join(snippets)[:500]


def validate_gold_dataset(
    gold_tuples_path: str | Path,
    gold_event_chains_path: str | Path,
    evidence_path: str | Path,
    events_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    hard_errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    gold_rows = read_jsonl(gold_tuples_path) if Path(gold_tuples_path).exists() else []
    chain_rows = read_jsonl(gold_event_chains_path) if Path(gold_event_chains_path).exists() else []
    events = read_jsonl(events_path)
    evidence = read_jsonl(evidence_path)
    event_ids = set(load_event_index(events))
    evidence_event = {str(row.get("evidence_id")): str(row.get("event_id")) for row in evidence if row.get("evidence_id")}
    seen: set[tuple[str, str, str, str, tuple[str, ...]]] = set()

    for index, row in enumerate(gold_rows, start=1):
        prefix = f"gold_tuple:{index}:{row.get('gold_tuple_id', '')}"
        event_id = str(row.get("event_id") or "")
        if event_id not in event_ids:
            hard_errors.append({"check": "event_id_exists", "row": prefix, "message": event_id})
        ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        if not ids:
            hard_errors.append({"check": "evidence_ids_nonempty", "row": prefix, "message": "missing"})
        for evidence_id in ids:
            if evidence_id not in evidence_event:
                hard_errors.append({"check": "evidence_id_exists", "row": prefix, "message": str(evidence_id)})
            elif evidence_event[evidence_id] != event_id:
                hard_errors.append({"check": "evidence_id_same_event", "row": prefix, "message": str(evidence_id)})
        if row.get("sentiment") not in SENTIMENTS:
            hard_errors.append({"check": "sentiment_valid", "row": prefix, "message": str(row.get("sentiment"))})
        if row.get("support_label") not in SUPPORT_LABELS:
            hard_errors.append({"check": "support_label_valid", "row": prefix, "message": str(row.get("support_label"))})
        for field in ("stakeholder", "opinion", "rationale"):
            if not str(row.get(field, "")).strip():
                hard_errors.append({"check": f"{field}_nonempty", "row": prefix, "message": "empty"})
        key = tuple_dedupe_key(row)
        if key in seen:
            hard_errors.append({"check": "duplicate_tuple", "row": prefix, "message": "|".join(key[:4])})
        seen.add(key)

    for index, row in enumerate(chain_rows, start=1):
        prefix = f"gold_event_chain:{index}:{row.get('gold_chain_id', '')}"
        event_id = str(row.get("event_id") or "")
        if event_id not in event_ids:
            hard_errors.append({"check": "chain_event_id_exists", "row": prefix, "message": event_id})
        nodes = row.get("event_chain") or row.get("chain_nodes") or row.get("nodes")
        if not nodes:
            hard_errors.append({"check": "chain_nodes_nonempty", "row": prefix, "message": "missing"})
        ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        if not ids:
            hard_errors.append({"check": "chain_evidence_ids_nonempty", "row": prefix, "message": "missing"})
        for evidence_id in ids:
            if evidence_id not in evidence_event:
                hard_errors.append({"check": "chain_evidence_id_exists", "row": prefix, "message": str(evidence_id)})
            elif evidence_event[evidence_id] != event_id:
                hard_errors.append({"check": "chain_evidence_id_same_event", "row": prefix, "message": str(evidence_id)})

    schema_valid = not hard_errors
    nonempty_gold = bool(gold_rows and chain_rows)
    report = {
        "valid": schema_valid,
        "schema_valid": schema_valid,
        "nonempty_gold": nonempty_gold,
        "ready_for_paper": schema_valid and nonempty_gold,
        "hard_error_count": len(hard_errors),
        "warning_count": len(warnings),
        "hard_errors": hard_errors,
        "warnings": warnings,
        "num_gold_tuples": len(gold_rows),
        "num_gold_event_chains": len(chain_rows),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "gold_validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def inspect_gold_samples(
    gold_tuples_path: str | Path,
    evidence_path: str | Path,
    gold_event_chains_path: str | Path | None = None,
    events_path: str | Path | None = None,
    num_events: int = 3,
    seed: int = 42,
    output_path: str | Path | None = None,
    event_id: str | None = None,
    limit: int | None = None,
    show_evidence: bool = True,
) -> str:
    import random

    tuples = read_jsonl(gold_tuples_path) if Path(gold_tuples_path).exists() else []
    chains = read_jsonl(gold_event_chains_path) if gold_event_chains_path and Path(gold_event_chains_path).exists() else []
    evidence_index = load_evidence_index(read_jsonl(evidence_path)) if Path(evidence_path).exists() else {}
    events = load_event_index(read_jsonl(events_path)) if events_path and Path(events_path).exists() else {}
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tuples:
        by_event[str(row.get("event_id") or "")].append(row)
    event_ids = [event_id] if event_id else sorted(by_event)
    random.Random(seed).shuffle(event_ids)
    event_ids = event_ids[: (limit or num_events)]
    chains_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chain in chains:
        chains_by_event[str(chain.get("event_id") or "")].append(chain)

    parts = ["# Gold Inspection Samples", ""]
    for eid in event_ids:
        parts.append(f"## {eid} {event_name(events.get(eid, {}))}".rstrip())
        for row in by_event.get(eid, [])[:5]:
            parts.append("")
            parts.append(f"- stakeholder: {row.get('stakeholder', '')}")
            parts.append(f"- opinion: {row.get('opinion', '')}")
            parts.append(f"- sentiment: {row.get('sentiment', '')}")
            parts.append(f"- rationale: {row.get('rationale', '')}")
            parts.append(f"- evidence_ids: {', '.join(row.get('evidence_ids', []) or [])}")
            if show_evidence:
                for evidence_id in row.get("evidence_ids", []) or []:
                    text = make_excerpt(evidence_index.get(evidence_id, {}).get("text", ""), 400)
                    parts.append(f"  - {evidence_id}: {text}")
        for chain in chains_by_event.get(eid, [])[:3]:
            nodes = chain.get("event_chain") or chain.get("chain_nodes") or []
            parts.append("")
            parts.append(f"- event_chain: {' -> '.join(str(node) for node in nodes)}")
            parts.append(f"- chain_evidence_ids: {', '.join(chain.get('evidence_ids', []) or [])}")
        parts.append("")
    text = "\n".join(parts).rstrip() + "\n"
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text, encoding="utf-8")
    return text
