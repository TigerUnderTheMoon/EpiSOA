"""Run LLM-assisted preannotation for gold tuple and event-chain review."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from episoa.config import load_config
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.llm.client import build_llm_client


SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "unclear"}
SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_preannotation(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LLM preannotation for PubEvent-SOA gold review.")
    parser.add_argument("--config", default="configs/paper.yaml")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence.jsonl")
    parser.add_argument("--output-dir", default="data/pubevent_soa_lite/annotation")
    parser.add_argument("--tuple-prompt", default="prompts/gold_tuple_preannotation.md")
    parser.add_argument("--chain-prompt", default="prompts/gold_chain_preannotation.md")
    parser.add_argument("--event-ids", default="")
    parser.add_argument("--max-events", type=int, default=1, help="Limit events for a smoke run. Use --all-events for a full formal pass.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based start offset after event-id filtering.")
    parser.add_argument("--all-events", action="store_true", help="Run preannotation for every event.")
    parser.add_argument("--retry-failed", action="store_true", help="Only rerun events/tasks that failed in the previous audit file.")
    parser.add_argument("--merge-existing", action="store_true", default=True, help="Merge this batch into existing outputs. Enabled by default.")
    parser.add_argument("--overwrite-output", action="store_true", help="Rewrite outputs with only the current batch results.")
    parser.add_argument("--audit-file", default="data/pubevent_soa_lite/annotation/llm_preannotation_audit.jsonl")
    parser.add_argument("--max-evidence", type=int, default=8)
    parser.add_argument("--max-evidence-chars", type=int, default=500)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_preannotation(args: argparse.Namespace) -> dict[str, Any]:
    events = select_events(
        read_jsonl(args.events),
        args.event_ids,
        None if args.all_events else args.max_events,
        start_index=args.start_index,
    )
    evidence_by_event = group_by_event(read_jsonl(args.evidence))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "llm_raw_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tuple_prompt = Path(args.tuple_prompt).read_text(encoding="utf-8")
    chain_prompt = Path(args.chain_prompt).read_text(encoding="utf-8")
    retry_tasks = load_retry_tasks(args.audit_file) if args.retry_failed else None
    if retry_tasks is not None:
        events = [event for event in events if str(event.get("event_id") or "") in retry_tasks]

    client = None
    model_name = "dry-run"
    api_error = ""
    if not args.dry_run:
        try:
            config = load_config(args.config)
            model_config = dict(config.model)
            model_config["temperature"] = args.temperature
            model_config["timeout_seconds"] = args.timeout_seconds
            model_config["max_retries"] = 0
            client = build_llm_client(model_config)
            model_name = client.model_name
        except Exception as exc:
            api_error = str(exc)

    tuples_path = output_dir / "llm_gold_tuples.jsonl"
    chains_path = output_dir / "llm_gold_event_chains.jsonl"
    audit_path = output_dir / "llm_preannotation_audit.jsonl"
    should_merge = bool(args.merge_existing) and not bool(args.overwrite_output)
    existing_tuples = load_existing_candidates(tuples_path) if should_merge else []
    existing_chains = load_existing_candidates(chains_path) if should_merge else []
    existing_audit = load_existing_candidates(audit_path) if should_merge else []
    existing_tuple_events_before_run = event_count(existing_tuples)
    existing_chain_events_before_run = event_count(existing_chains)
    batch_tuples: list[dict[str, Any]] = []
    batch_chains: list[dict[str, Any]] = []
    audit_records: list[dict[str, Any]] = []

    for event in events:
        event_id = str(event.get("event_id") or "")
        evidence_items, pack_warning = select_evidence_pack(
            evidence_by_event.get(event_id, []),
            max_evidence=args.max_evidence,
            max_chars=args.max_evidence_chars,
        )
        if not evidence_items:
            audit_records.append(
                audit_record(
                    event_id=event_id,
                    task_type="tuple",
                    model_name=model_name,
                    request_status="skipped",
                    parse_status="not_run",
                    num_candidates=0,
                    error_type="no_evidence",
                    error_message="No evidence rows found for event.",
                    raw_response_path="",
                    evidence_count=0,
                    evidence_truncated=False,
                )
            )
            continue
        context = build_event_context(event, evidence_items)
        for task, prompt_template in (("tuple", tuple_prompt), ("chain", chain_prompt)):
            if retry_tasks is not None and task not in retry_tasks.get(event_id, set()):
                continue
            prompt = prompt_template.replace("{{EVENT_CONTEXT_JSON}}", context)
            if args.dry_run or client is None:
                audit_records.append(
                    audit_record(
                        event_id=event_id,
                        task_type=task,
                        model_name=model_name,
                        request_status="skipped",
                        parse_status="not_run",
                        num_candidates=0,
                        error_type="dry_run" if args.dry_run else "api_setup_error",
                        error_message=api_error or "dry_run",
                        raw_response_path="",
                        evidence_count=len(evidence_items),
                        evidence_truncated=bool(pack_warning),
                        warning=pack_warning,
                    )
                )
                continue
            response, request_error = call_with_retries(
                client,
                system_prompt="You are a careful PubEvent-SOA gold annotation assistant. Return JSON only.",
                user_prompt=prompt,
                max_attempts=max(1, int(args.max_retries) + 1),
            )
            raw_path = raw_response_path(raw_dir, event_id, task)
            if request_error:
                write_raw_response(raw_path, "")
                audit_records.append(
                    audit_record(
                        event_id=event_id,
                        task_type=task,
                        model_name=model_name,
                        request_status="failed",
                        parse_status="not_run",
                        num_candidates=0,
                        error_type=classify_error(request_error),
                        error_message=request_error,
                        raw_response_path=str(raw_path),
                        evidence_count=len(evidence_items),
                        evidence_truncated=bool(pack_warning),
                        warning=pack_warning,
                    )
                )
                continue
            assert response is not None
            write_raw_response(raw_path, response.content)
            parsed, parse_error = parse_payload(
                response.content,
                event_id,
                {str(item.get("evidence_id")) for item in evidence_items},
                task,
            )
            parse_status = "failed" if parse_error else "parsed"
            request_status = "ok"
            error_type = classify_parse_error(parse_error) if parse_error else ""
            audit_records.append(
                audit_record(
                    event_id=event_id,
                    task_type=task,
                    model_name=model_name,
                    request_status=request_status,
                    parse_status=parse_status,
                    num_candidates=len(parsed),
                    error_type=error_type,
                    error_message=parse_error,
                    raw_response_path=str(raw_path),
                    evidence_count=len(evidence_items),
                    evidence_truncated=bool(pack_warning),
                    response_id=response.response_id,
                    warning=pack_warning,
                )
            )
            if parse_error:
                continue
            if task == "tuple":
                batch_tuples.extend(parsed)
            else:
                batch_chains.extend(parsed)

    tuples = merge_candidates(
        existing_tuples,
        batch_tuples,
        key_fields=("event_id", "candidate_id"),
        replace_event_ids=successful_event_ids(audit_records, "tuple"),
    )
    chains = merge_candidates(
        existing_chains,
        batch_chains,
        key_fields=("event_id", "candidate_chain_id"),
        replace_event_ids=successful_event_ids(audit_records, "chain"),
    )
    write_jsonl(tuples_path, tuples)
    write_jsonl(chains_path, chains)
    merged_audit_records = existing_audit + audit_records
    failed_events = sorted({row["event_id"] for row in audit_records if row["request_status"] == "failed" or row["parse_status"] == "failed"})
    report = {
        "num_events": len(events),
        "attempted_events": len({row["event_id"] for row in audit_records}),
        "successful_tuple_events": len({row["event_id"] for row in audit_records if row["task_type"] == "tuple" and row["request_status"] == "ok" and row["parse_status"] == "parsed"}),
        "successful_chain_events": len({row["event_id"] for row in audit_records if row["task_type"] == "chain" and row["request_status"] == "ok" and row["parse_status"] == "parsed"}),
        "failed_events": failed_events,
        "failed_event_count": len(failed_events),
        "num_llm_gold_tuples": len(tuples),
        "num_llm_gold_event_chains": len(chains),
        "total_tuple_candidates": len(tuples),
        "total_chain_candidates": len(chains),
        "batch_tuple_candidates": len(batch_tuples),
        "batch_chain_candidates": len(batch_chains),
        "existing_tuple_events_before_run": existing_tuple_events_before_run,
        "existing_chain_events_before_run": existing_chain_events_before_run,
        "merged_tuple_events_after_run": event_count(tuples),
        "merged_chain_events_after_run": event_count(chains),
        "api_failures": sum(1 for row in audit_records if row["request_status"] == "failed"),
        "parse_failures": sum(1 for row in audit_records if row["parse_status"] == "failed"),
        "model_name": model_name,
        "temperature": args.temperature,
        "max_evidence": args.max_evidence,
        "max_evidence_chars": args.max_evidence_chars,
        "start_index": args.start_index,
        "retry_failed": bool(args.retry_failed),
        "merge_existing": should_merge,
        "overwrite_output": bool(args.overwrite_output),
        "dry_run": bool(args.dry_run),
        "api_setup_error": api_error,
        "output_files": {
            "llm_gold_tuples": str(output_dir / "llm_gold_tuples.jsonl"),
            "llm_gold_event_chains": str(output_dir / "llm_gold_event_chains.jsonl"),
            "llm_preannotation_report": str(output_dir / "llm_preannotation_report.json"),
            "llm_preannotation_audit": str(output_dir / "llm_preannotation_audit.jsonl"),
            "raw_response_dir": str(raw_dir),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_jsonl(audit_path, merged_audit_records)
    write_jsonl(output_dir / "llm_gold_raw_responses.jsonl", legacy_raw_records(merged_audit_records))
    (output_dir / "llm_preannotation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def select_events(
    events: list[dict[str, Any]],
    event_ids: str,
    max_events: int | None,
    start_index: int = 0,
) -> list[dict[str, Any]]:
    allowed = {item.strip() for item in event_ids.split(",") if item.strip()}
    rows = [event for event in events if not allowed or str(event.get("event_id")) in allowed]
    if start_index > 0:
        rows = rows[start_index:]
    return rows[:max_events] if max_events is not None else rows


def group_by_event(evidence: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        grouped[str(row.get("event_id") or "")].append(row)
    return grouped


def select_evidence_pack(
    evidence_items: list[dict[str, Any]],
    *,
    max_evidence: int,
    max_chars: int,
) -> tuple[list[dict[str, Any]], str]:
    def sort_key(row: dict[str, Any]) -> tuple[float, str]:
        try:
            quality = float(row.get("quality_score") or 0)
        except (TypeError, ValueError):
            quality = 0.0
        return (-quality, str(row.get("publish_time") or ""))

    sorted_rows = sorted(evidence_items, key=sort_key)
    selected = sorted_rows[:max_evidence]
    warning = ""
    if len(evidence_items) > len(selected):
        warning = f"evidence pack truncated from {len(evidence_items)} to {len(selected)} rows"
    clipped: list[dict[str, Any]] = []
    clipped_count = 0
    for row in selected:
        item = dict(row)
        text = str(item.get("text") or "")
        if len(text) > max_chars:
            item["text"] = text[:max_chars] + "..."
            clipped_count += 1
        clipped.append(item)
    if clipped_count:
        warning = (warning + "; " if warning else "") + f"{clipped_count} evidence texts clipped to {max_chars} chars"
    return clipped, warning


def build_event_context(event: dict[str, Any], evidence_items: list[dict[str, Any]]) -> str:
    payload = {
        "event": event,
        "evidence": [
            {
                "evidence_id": row.get("evidence_id"),
                "source": row.get("source"),
                "domain": row.get("domain") or row.get("platform"),
                "publish_time": row.get("publish_time"),
                "url": row.get("url"),
                "text": row.get("text"),
            }
            for row in evidence_items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_payload(text: str, event_id: str, allowed_evidence_ids: set[str], task: str) -> tuple[list[dict[str, Any]], str]:
    if not text.strip():
        return [], "empty_llm_content"
    try:
        payload = json.loads(extract_json_object(text))
    except (json.JSONDecodeError, ValueError) as exc:
        return [], f"invalid_json:{exc}"
    if not isinstance(payload, dict):
        return [], "payload_not_object"
    if str(payload.get("event_id") or "") != event_id:
        return [], "event_id_mismatch"
    key = "tuples" if task == "tuple" else "event_chains"
    rows = payload.get(key, [])
    if not isinstance(rows, list):
        return [], f"{key}_not_list"
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        raw_ids = row.get("evidence_ids", [])
        if not isinstance(raw_ids, list):
            return [], f"{task}_candidate_{index}_evidence_ids_not_list"
        ids = dedupe([str(eid) for eid in raw_ids if str(eid) in allowed_evidence_ids])
        if not ids:
            return [], f"{task}_candidate_{index}_missing_valid_evidence_ids"
        if any(str(eid) not in allowed_evidence_ids for eid in raw_ids):
            return [], f"{task}_candidate_{index}_unknown_evidence_id"
        if task == "tuple":
            support = str(row.get("support_label") or "supported")
            sentiment = str(row.get("sentiment") or "unknown")
            if support not in SUPPORT_LABELS or sentiment not in SENTIMENTS:
                return [], f"tuple_candidate_{index}_invalid_label"
            if not all(str(row.get(field) or "").strip() for field in ("stakeholder", "opinion", "rationale")):
                return [], f"tuple_candidate_{index}_missing_required_field"
            parsed.append(
                {
                    "event_id": event_id,
                    "candidate_id": f"LLM_{event_id}_{index:03d}",
                    "source_type": "llm_preannotation",
                    "stakeholder": row["stakeholder"],
                    "opinion": row["opinion"],
                    "sentiment": sentiment,
                    "rationale": row["rationale"],
                    "evidence_ids": ids,
                    "support_label": support,
                }
            )
        else:
            chain = row.get("event_chain") or row.get("chain_nodes") or []
            if isinstance(chain, str):
                chain = [part.strip() for part in chain.split(";") if part.strip()]
            if not isinstance(chain, list) or not chain:
                return [], f"chain_candidate_{index}_missing_event_chain"
            parsed.append(
                {
                    "event_id": event_id,
                    "candidate_chain_id": f"LLM_CHAIN_{event_id}_{index:03d}",
                    "source_type": "llm_preannotation",
                    "event_chain": [str(item) for item in chain if str(item).strip()],
                    "evidence_ids": ids,
                }
            )
    return parsed, ""


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no_json_object")
    return stripped[start : end + 1]


def dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def call_with_retries(
    client: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    max_attempts: int,
) -> tuple[Any | None, str]:
    last_error = ""
    for attempt in range(max_attempts):
        try:
            return (
                client.chat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format={"type": "json_object"},
                ),
                "",
            )
        except Exception as exc:
            last_error = str(exc)
            if attempt + 1 < max_attempts:
                time.sleep(min(2, attempt + 1))
    return None, last_error


def classify_error(message: str) -> str:
    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "api_timeout"
    if "api_key" in lowered or "401" in lowered or "403" in lowered:
        return "api_auth"
    if "rate" in lowered or "429" in lowered:
        return "api_rate_limit"
    if not message:
        return ""
    return "api_error"


def classify_parse_error(message: str) -> str:
    if not message:
        return ""
    if message.startswith("invalid_json") or "json" in message:
        return "invalid_json"
    if "evidence" in message:
        return "invalid_evidence_ids"
    if "label" in message:
        return "invalid_label"
    return "parse_error"


def raw_response_path(raw_dir: Path, event_id: str, task: str) -> Path:
    safe_event = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in event_id)
    return raw_dir / f"{safe_event}_{task}.txt"


def write_raw_response(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_retry_tasks(audit_file: str | Path) -> dict[str, set[str]]:
    path = Path(audit_file)
    if not path.exists():
        return {}
    tasks: dict[str, set[str]] = defaultdict(set)
    for row in read_jsonl(path):
        if row.get("request_status") == "failed" or row.get("parse_status") == "failed":
            event_id = str(row.get("event_id") or "")
            task = str(row.get("task_type") or row.get("task") or "")
            if event_id and task in {"tuple", "chain"}:
                tasks[event_id].add(task)
    return tasks


def load_existing_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def event_count(rows: list[dict[str, Any]]) -> int:
    return len({str(row.get("event_id") or "") for row in rows if row.get("event_id")})


def successful_event_ids(audit_records: list[dict[str, Any]], task_type: str) -> set[str]:
    return {
        str(row.get("event_id") or "")
        for row in audit_records
        if row.get("task_type") == task_type
        and row.get("request_status") == "ok"
        and row.get("parse_status") == "parsed"
    }


def merge_candidates(
    existing_rows: list[dict[str, Any]],
    batch_rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    replace_event_ids: set[str],
) -> list[dict[str, Any]]:
    kept = [row for row in existing_rows if str(row.get("event_id") or "") not in replace_event_ids]
    return dedupe_candidates([*kept, *batch_rows], key_fields=key_fields)


def dedupe_candidates(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key_values: list[str] = []
        for field in key_fields:
            value = row.get(field)
            if isinstance(value, list):
                value = "|".join(str(item) for item in value)
            key_values.append(str(value or "").strip().lower())
        key = tuple(key_values)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def legacy_raw_records(audit_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in audit_records:
        raw_path = row.get("raw_response_path")
        raw_response = Path(raw_path).read_text(encoding="utf-8") if raw_path and Path(raw_path).exists() else ""
        rows.append(
            {
                "event_id": row.get("event_id", ""),
                "task": row.get("task_type", ""),
                "model_name": row.get("model_name", ""),
                "response_id": row.get("response_id", ""),
                "raw_response": raw_response,
                "parse_success": row.get("parse_status") == "parsed",
                "parse_error": row.get("error_message", ""),
                "created_at": row.get("created_at", ""),
            }
        )
    return rows


def audit_record(
    *,
    event_id: str,
    task_type: str,
    model_name: str,
    request_status: str,
    parse_status: str,
    num_candidates: int,
    error_type: str,
    error_message: str,
    raw_response_path: str,
    evidence_count: int,
    evidence_truncated: bool,
    response_id: str = "",
    warning: str = "",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "task_type": task_type,
        "request_status": request_status,
        "parse_status": parse_status,
        "num_candidates": num_candidates,
        "error_type": error_type,
        "error_message": error_message,
        "raw_response_path": raw_response_path,
        "evidence_count": evidence_count,
        "evidence_truncated": evidence_truncated,
        "warning": warning,
        "model_name": model_name,
        "response_id": response_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
