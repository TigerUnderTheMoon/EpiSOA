"""LLM-driven schema-constrained stakeholder opinion attribution."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl


PROMPT_VERSION = "schema_attribution_v2_json"
MAX_TUPLES_PER_EVENT = 4
MAX_OPINION_CHARS = 40
MAX_RATIONALE_CHARS = 60
ALLOWED_SENTIMENT = {"positive", "negative", "neutral"}
ALLOWED_STAGE = {"trigger", "diffusion", "conflict", "response", "resolution", "follow_up", "mixed", "unknown"}
ALLOWED_SUPPORT = {"candidate_supported", "candidate_partially_supported", "candidate_unclear"}
STAGE_PRIORITY = ["conflict", "response", "resolution", "trigger", "diffusion", "follow_up"]

SYSTEM_PROMPT = """You are an information extraction system for evidence-grounded stakeholder opinion attribution in public events.
You must extract stakeholder-opinion-sentiment-rationale tuples only from the provided evidence.
Do not use external knowledge.
Do not invent stakeholders, opinions, rationales, or evidence IDs.
Return strict JSON only.
If the evidence is insufficient, return an empty tuples list.
The first character must be { and the last character must be }."""


USER_PROMPT_TEMPLATE = """任务：
请基于给定公共事件、候选事件链和证据文本，抽取“主体—观点—情绪—依据”结构化元组。

要求：
1. 只能使用下方 evidence 中的信息，不能使用外部知识。
2. 不能编造 evidence_id、主体、观点或依据。
3. 如果只是泛化政策、背景介绍、无法判断具体主体观点，则返回空 tuples。
4. 官方通报、说明、答复可标为“政府部门”或更具体部门。
5. 家长、居民、网友、学生、消费者等表达质疑、不满、投诉时，归为相应主体。
6. sentiment 只能为 positive、negative、neutral。
7. 官方通报、政策发布、监管回应、调查处理、机制完善等治理行为，sentiment 默认标为 neutral。
8. 只有证据中明确出现支持、满意、认可、赞扬、欢迎等态度表达时，才标为 positive。
9. 如果主体只是发布政策、说明情况、开展调查、提出整改、加强监管，不应标为 positive，应标为 neutral。
10. stakeholder 名称尽量规范化，例如“国务院食安办等五部门”可归为“监管部门”或“多部门联合监管主体”，避免过长机构名导致 stakeholder_distribution 过碎。

重要输出限制：
1. 每个事件最多输出 4 条 tuples。
2. 每条 tuple 的 opinion 不超过 40 个中文字符。
3. 每条 tuple 的 rationale 不超过 60 个中文字符。
4. 不要输出 evidence 原文全文。
5. 只输出一个 JSON 对象。
6. 不要输出 Markdown。
7. 第一个字符必须是 {{，最后一个字符必须是 }}。

事件信息：
event_id: {event_id}
event_name: {event_name}
event_description: {event_description}
seed_keywords: {seed_keywords}
stakeholder_hints: {stakeholder_hints}

候选事件链摘要：
chain_confidence: {chain_confidence}
missing_stages: {missing_stages}

阶段证据：
{stage_evidence_blocks}

主体候选：
{stakeholder_candidates}

请输出严格 JSON：
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder": "主体名称",
      "opinion": "不超过40个中文字符",
      "sentiment": "positive|negative|neutral",
      "rationale": "不超过60个中文字符",
      "evidence_ids": ["只能使用上方出现过的 evidence_id"],
      "event_chain_stage": "trigger|diffusion|conflict|response|resolution|follow_up|mixed|unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0
    }}
  ]
}}"""


RETRY_USER_PROMPT_TEMPLATE = """只根据下面 evidence 抽取最多 4 条主体观点元组。输出一个严格 JSON 对象，不能输出 Markdown 或解释文字。第一个字符必须是 {{，最后一个字符必须是 }}。

event_id: {event_id}
event_name: {event_name}

evidence:
{stage_evidence_blocks}

JSON schema:
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder": "主体",
      "opinion": "不超过40个中文字符",
      "sentiment": "positive|negative|neutral",
      "rationale": "不超过60个中文字符",
      "evidence_ids": ["上方存在的 evidence_id"],
      "event_chain_stage": "trigger|diffusion|conflict|response|resolution|follow_up|mixed|unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0
    }}
  ]
}}"""


@dataclass
class ParseResult:
    tuples: list[dict[str, Any]]
    parse_success: bool
    parse_error: str | None = None


class SchemaAttributor:
    def __init__(
        self,
        *,
        llm_client: Any | None,
        model_name: str,
        prompt_version: str = PROMPT_VERSION,
        max_tuples_per_event: int = MAX_TUPLES_PER_EVENT,
    ):
        self.llm_client = llm_client
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.max_tuples_per_event = max_tuples_per_event

    def build_prompt(
        self,
        *,
        event: dict[str, Any],
        chain: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
    ) -> tuple[str, str]:
        stage_evidence_blocks = format_stage_evidence_blocks(evidence_items)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            event_id=event.get("event_id", ""),
            event_name=event.get("event_name", ""),
            event_description=event.get("event_description", ""),
            seed_keywords=json.dumps(event.get("seed_keywords", []), ensure_ascii=False),
            stakeholder_hints=json.dumps(event.get("stakeholder_hints", []), ensure_ascii=False),
            chain_confidence=chain.get("chain_confidence", 0),
            missing_stages=json.dumps(chain.get("missing_stages", []), ensure_ascii=False),
            stage_evidence_blocks=stage_evidence_blocks,
            stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
        )
        return SYSTEM_PROMPT, user_prompt

    def build_retry_prompt(self, *, event: dict[str, Any], evidence_items: list[dict[str, Any]]) -> tuple[str, str]:
        stage_evidence_blocks = format_stage_evidence_blocks(evidence_items, max_excerpt_chars=220)
        return SYSTEM_PROMPT, RETRY_USER_PROMPT_TEMPLATE.format(
            event_id=event.get("event_id", ""),
            event_name=event.get("event_name", ""),
            stage_evidence_blocks=stage_evidence_blocks,
        )

    def attribute_event(
        self,
        *,
        event: dict[str, Any],
        chain: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        dry_run: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        system_prompt, user_prompt = self.build_prompt(
            event=event,
            chain=chain,
            evidence_items=evidence_items,
            stakeholder_candidates=stakeholder_candidates,
        )
        event_id = str(event.get("event_id", ""))
        request_summary = {
            "num_evidence": len(evidence_items),
            "chain_confidence": chain.get("chain_confidence", 0),
            "prompt_chars": len(system_prompt) + len(user_prompt),
            "api_calls_made": 0,
            "json_mode": True,
        }
        if dry_run:
            preview = user_prompt[:2500]
            safe_console_print(f"\n--- prompt preview: {event_id} ---\n{preview}\n--- end prompt preview: {event_id} ---\n")
            return [], raw_record(
                event_id=event_id,
                model_name=self.model_name,
                request_summary=request_summary,
                raw_response="",
                parse_success=True,
                parse_error=None,
                dry_run=True,
            )
        if self.llm_client is None:
            raise RuntimeError("llm_client is required unless dry_run=True")

        allowed_evidence_ids = {str(item["evidence_id"]) for item in evidence_items if item.get("evidence_id")}
        response = self.llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
        )
        request_summary["api_calls_made"] = 1
        parsed = self._parse_llm_response(response, event_id, allowed_evidence_ids)
        raw_response_text = normalize_raw_response(response)
        raw_response_id = getattr(response, "response_id", "")

        if parsed.parse_error == "empty_llm_content":
            retry_system_prompt, retry_user_prompt = self.build_retry_prompt(event=event, evidence_items=evidence_items)
            retry_response = self.llm_client.chat(
                system_prompt=retry_system_prompt,
                user_prompt=retry_user_prompt,
                response_format={"type": "json_object"},
            )
            request_summary["api_calls_made"] = 2
            request_summary["retried_after_empty_content"] = True
            parsed = self._parse_llm_response(retry_response, event_id, allowed_evidence_ids)
            raw_response_text = normalize_raw_response(retry_response)
            raw_response_id = getattr(retry_response, "response_id", "")

        return parsed.tuples, raw_record(
            event_id=event_id,
            model_name=self.model_name,
            request_summary=request_summary,
            raw_response=raw_response_text,
            parse_success=parsed.parse_success,
            parse_error=parsed.parse_error,
        )

    def _parse_llm_response(self, response: Any, event_id: str, allowed_evidence_ids: set[str]) -> ParseResult:
        return parse_response(
            response,
            event_id=event_id,
            allowed_evidence_ids=allowed_evidence_ids,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response_id=getattr(response, "response_id", ""),
            max_tuples=self.max_tuples_per_event,
        )


def run_schema_attribution(
    *,
    events: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    graph_nodes: list[dict[str, Any]],
    llm_client: Any | None,
    model_name: str,
    output_dir: str | Path,
    event_ids: list[str] | None = None,
    max_events: int | None = None,
    max_evidence_per_event: int = 12,
    dry_run: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_events = select_events(events, event_ids=event_ids, max_events=max_events)
    chains_by_event = {str(chain.get("event_id", "")): chain for chain in chains}
    evidence_by_event = group_by_event(evidence_rows)
    stakeholders_by_event = stakeholder_candidates_by_event(graph_nodes)
    attributor = SchemaAttributor(llm_client=llm_client, model_name=model_name)

    tuples: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    no_chain_context_events: list[str] = []
    empty_tuple_events: list[str] = []
    parse_failed_events: list[str] = []
    api_failures = 0
    api_calls = 0

    for event in selected_events:
        event_id = str(event.get("event_id", ""))
        chain = chains_by_event.get(event_id)
        if chain is None:
            no_chain_context_events.append(event_id)
            chain = {}  # use empty chain so select_prompt_evidence falls back to quality_score
        elif float(chain.get("chain_confidence", 0) or 0) <= 0:
            no_chain_context_events.append(event_id)
        stakeholder_candidates = stakeholders_by_event.get(event_id) or stakeholders_by_event.get("__global__", [])
        evidence_items = select_prompt_evidence(
            event=event,
            chain=chain,
            evidence_rows=evidence_by_event.get(event_id, []),
            max_evidence=max_evidence_per_event,
        )
        if not evidence_items:
            no_chain_context_events.append(event_id)
            continue
        try:
            event_tuples, record = attributor.attribute_event(
                event=event,
                chain=chain,
                evidence_items=evidence_items,
                stakeholder_candidates=stakeholder_candidates,
                dry_run=dry_run,
            )
            raw_records.append(record)
            api_calls += int(record.get("request_summary", {}).get("api_calls_made", 0) or 0)
            if record.get("parse_success") is False:
                parse_failed_events.append(event_id)
            if not event_tuples:
                empty_tuple_events.append(event_id)
            tuples.extend(event_tuples)
        except Exception as exc:
            api_failures += 1
            raw_records.append(
                raw_record(
                    event_id=event_id,
                    model_name=model_name,
                    request_summary={"num_evidence": len(evidence_items), "api_calls_made": 0},
                    raw_response="",
                    parse_success=False,
                    parse_error=str(exc),
                )
            )

    candidates_path = output_dir / "candidate_soa_tuples.jsonl"
    raw_path = output_dir / "raw_llm_responses.jsonl"
    table_path = output_dir / "schema_attribution_table.csv"
    summary_path = output_dir / "schema_attribution_summary.json"

    write_jsonl(candidates_path, tuples)
    write_jsonl(raw_path, raw_records)
    write_tuple_table(table_path, tuples)
    summary = build_summary(
        requested=len(selected_events),
        processed=len(selected_events) - len(no_chain_context_events),
        tuples=tuples,
        api_calls=api_calls,
        api_failures=api_failures,
        no_chain_context_events=no_chain_context_events,
        empty_tuple_events=empty_tuple_events,
        parse_failed_events=parse_failed_events,
        model_name=model_name,
        output_path=str(candidates_path),
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_response(
    raw_response: Any,
    *,
    event_id: str,
    allowed_evidence_ids: set[str],
    model_name: str,
    prompt_version: str = PROMPT_VERSION,
    raw_response_id: str = "",
    max_tuples: int = MAX_TUPLES_PER_EVENT,
) -> ParseResult:
    text = normalize_raw_response(raw_response)
    if not text.strip():
        return ParseResult([], False, "empty_llm_content")
    try:
        json_text = extract_json_object(text)
    except ValueError as exc:
        return ParseResult([], False, str(exc))
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return ParseResult([], False, "incomplete_or_malformed_json")
    if not isinstance(payload, dict):
        return ParseResult([], False, "response JSON must be an object")
    if str(payload.get("event_id", "")) != event_id:
        return ParseResult([], False, f"event_id mismatch: {payload.get('event_id')}")
    tuples_value = payload.get("tuples", [])
    if not isinstance(tuples_value, list):
        return ParseResult([], False, "tuples must be a list")

    output: list[dict[str, Any]] = []
    for row in tuples_value:
        if not isinstance(row, dict):
            continue
        sentiment = str(row.get("sentiment", "")).strip()
        if sentiment not in ALLOWED_SENTIMENT:
            continue
        stage = str(row.get("event_chain_stage") or "unknown").strip()
        if stage not in ALLOWED_STAGE:
            stage = "unknown"
        support = str(row.get("support_status") or "candidate_unclear").strip()
        if support not in ALLOWED_SUPPORT:
            support = "candidate_unclear"
        evidence_ids = dedupe(
            [str(eid) for eid in row.get("evidence_ids", []) if str(eid) in allowed_evidence_ids]
        )
        if not evidence_ids:
            continue
        stakeholder = str(row.get("stakeholder", "")).strip()
        opinion = truncate_text(row.get("opinion", ""), MAX_OPINION_CHARS)
        rationale = truncate_text(row.get("rationale", ""), MAX_RATIONALE_CHARS)
        if not stakeholder or not opinion or not rationale:
            continue
        output.append(
            {
                "event_id": event_id,
                "tuple_id": f"{event_id}_SOA_{len(output) + 1:03d}",
                "stakeholder": stakeholder,
                "opinion": opinion,
                "sentiment": sentiment,
                "rationale": rationale,
                "evidence_ids": evidence_ids,
                "event_chain_stage": stage,
                "support_status": support,
                "confidence": clamp_float(row.get("confidence", 0.0)),
                "model_name": model_name,
                "prompt_version": prompt_version,
                "raw_response_id": raw_response_id,
                "created_at": now_iso(),
            }
        )
        if len(output) >= max_tuples:
            break
    return ParseResult(output, True, None)


def select_events(events: list[dict[str, Any]], *, event_ids: list[str] | None, max_events: int | None) -> list[dict[str, Any]]:
    selected = events
    if event_ids:
        wanted = set(event_ids)
        selected = [event for event in selected if str(event.get("event_id", "")) in wanted]
    if max_events is not None and max_events > 0:
        selected = selected[:max_events]
    return selected


def select_prompt_evidence(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    max_evidence: int,
) -> list[dict[str, Any]]:
    evidence_by_id = {str(row.get("evidence_id", "")): row for row in evidence_rows}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    stage_blocks = {stage.get("stage"): stage for stage in chain.get("stages", []) if isinstance(stage, dict)}
    for stage_name in STAGE_PRIORITY:
        stage = stage_blocks.get(stage_name, {})
        ranked = sorted(
            stage.get("evidence", []),
            key=lambda item: (
                float(item.get("final_stage_score", item.get("score", 0)) or 0),
                float(item.get("event_relevance_score", 0) or 0),
            ),
            reverse=True,
        )[:2]
        for item in ranked:
            evidence_id = str(item.get("evidence_id", ""))
            if not evidence_id or evidence_id in seen:
                continue
            row = evidence_by_id.get(evidence_id, {})
            selected.append(normalize_prompt_evidence(item, row, stage_name))
            seen.add(evidence_id)
            if len(selected) >= max_evidence:
                return selected

    fallback = sorted(evidence_rows, key=lambda row: float(row.get("quality_score", 0) or 0), reverse=True)
    for row in fallback:
        evidence_id = str(row.get("evidence_id", ""))
        if not evidence_id or evidence_id in seen:
            continue
        selected.append(normalize_prompt_evidence({"evidence_id": evidence_id, "stage": "unknown"}, row, "unknown"))
        seen.add(evidence_id)
        if len(selected) >= max_evidence:
            break
    return selected


def normalize_prompt_evidence(chain_item: dict[str, Any], row: dict[str, Any], stage: str) -> dict[str, Any]:
    text = str(row.get("text") or chain_item.get("text_excerpt") or "")
    return {
        "evidence_id": chain_item.get("evidence_id") or row.get("evidence_id"),
        "stage": stage,
        "source": row.get("source") or chain_item.get("source", ""),
        "domain": row.get("domain") or chain_item.get("domain", ""),
        "url": row.get("url") or chain_item.get("url", ""),
        "title": row.get("title") or chain_item.get("title", ""),
        "text_excerpt": chain_item.get("text_excerpt") or text[:500],
        "final_stage_score": chain_item.get("final_stage_score", chain_item.get("score", "")),
        "event_relevance_score": chain_item.get("event_relevance_score", ""),
    }


def format_stage_evidence_blocks(evidence_items: list[dict[str, Any]], *, max_excerpt_chars: int = 360) -> str:
    lines: list[str] = []
    for item in evidence_items:
        lines.append(
            "\n".join(
                [
                    f"- evidence_id: {item.get('evidence_id')}",
                    f"  stage: {item.get('stage')}",
                    f"  source: {item.get('source')}",
                    f"  domain: {item.get('domain')}",
                    f"  url: {item.get('url')}",
                    f"  title: {truncate_text(item.get('title', ''), 80)}",
                    f"  final_stage_score: {item.get('final_stage_score')}",
                    f"  event_relevance_score: {item.get('event_relevance_score')}",
                    f"  text_excerpt: {truncate_text(item.get('text_excerpt', ''), max_excerpt_chars)}",
                ]
            )
        )
    return "\n".join(lines) if lines else "无可用 evidence。"


def stakeholder_candidates_by_event(graph_nodes: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_event: dict[str, set[str]] = {}
    global_candidates: set[str] = set()
    for node in graph_nodes:
        node_type = node.get("node_type")
        node_id = str(node.get("node_id", ""))
        attrs = node.get("attributes", {}) if isinstance(node.get("attributes", {}), dict) else {}
        if node_type != "stakeholder_candidate" and not node_id.startswith("stakeholder:"):
            continue
        name = str(attrs.get("stakeholder") or attrs.get("name") or node_id.replace("stakeholder:", "")).strip()
        if not name:
            continue
        global_candidates.add(name)
        event_id = attrs.get("event_id")
        if event_id:
            by_event.setdefault(str(event_id), set()).add(name)
    return {event_id: sorted(values | global_candidates) for event_id, values in by_event.items()} | {"__global__": sorted(global_candidates)}


def group_by_event(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("event_id", "")), []).append(row)
    return grouped


def build_summary(
    *,
    requested: int,
    processed: int,
    tuples: list[dict[str, Any]],
    api_calls: int,
    api_failures: int,
    no_chain_context_events: list[str],
    empty_tuple_events: list[str],
    parse_failed_events: list[str],
    model_name: str,
    output_path: str,
) -> dict[str, Any]:
    confidences = [float(row.get("confidence", 0) or 0) for row in tuples]
    return {
        "num_events_requested": requested,
        "num_events_processed": processed,
        "num_events_skipped": requested - processed,
        "num_tuples_generated": len(tuples),
        "num_api_calls": api_calls,
        "num_api_failures": api_failures,
        "no_chain_context_events": no_chain_context_events,
        "empty_tuple_events": empty_tuple_events,
        "parse_failed_events": parse_failed_events,
        "sentiment_distribution": dict(Counter(row["sentiment"] for row in tuples)),
        "stakeholder_distribution": dict(Counter(row["stakeholder"] for row in tuples)),
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "output_path": output_path,
        "model_name": model_name,
        "prompt_version": PROMPT_VERSION,
    }


def write_tuple_table(path: str | Path, tuples: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_id",
        "tuple_id",
        "stakeholder",
        "opinion",
        "sentiment",
        "rationale",
        "evidence_ids",
        "event_chain_stage",
        "support_status",
        "confidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in tuples:
            flat = dict(row)
            flat["evidence_ids"] = "|".join(row.get("evidence_ids", []))
            writer.writerow(flat)


def read_graph_nodes(graph_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(graph_dir) / "evidence_graph_nodes.jsonl"
    return read_jsonl(path) if path.exists() else []


def read_chains(path: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def normalize_raw_response(raw_response: Any) -> str:
    if raw_response is None:
        return ""
    if isinstance(raw_response, str):
        return raw_response
    if hasattr(raw_response, "content"):
        return str(getattr(raw_response, "content") or "")
    if isinstance(raw_response, dict):
        if "choices" in raw_response:
            try:
                return str(raw_response["choices"][0]["message"].get("content") or "")
            except (KeyError, IndexError, TypeError, AttributeError):
                return json.dumps(raw_response, ensure_ascii=False)
        if "content" in raw_response:
            return str(raw_response.get("content") or "")
        return json.dumps(raw_response, ensure_ascii=False)
    return str(raw_response)


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped).strip()
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    if start >= 0:
        raise ValueError("incomplete_or_malformed_json")
    raise ValueError("no JSON object found")


def raw_record(
    *,
    event_id: str,
    model_name: str,
    request_summary: dict[str, Any],
    raw_response: str,
    parse_success: bool,
    parse_error: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    record = {
        "event_id": event_id,
        "model_name": model_name,
        "prompt_version": PROMPT_VERSION,
        "request_summary": request_summary,
        "raw_response": raw_response,
        "parse_success": parse_success,
        "parse_error": parse_error,
    }
    if dry_run:
        record["dry_run"] = True
    return record


def truncate_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


def clamp_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_console_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    sys.stdout.flush()
