"""LLM-assisted evidence faithfulness verification for candidate SOA tuples."""

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

from episoa.data.loader import write_jsonl


VERIFIER_PROMPT_VERSION = "faithfulness_verification_v1_json"
ALLOWED_LABELS = {"supported", "partially_supported", "unsupported", "unclear"}
ALLOWED_ISSUE_FLAGS = {
    "missing_evidence",
    "weak_evidence",
    "sentiment_not_supported",
    "stakeholder_not_supported",
    "opinion_overgeneralized",
    "rationale_not_supported",
    "stage_mismatch",
    "official_action_should_be_neutral",
    "media_comment_should_be_neutral",
    "no_issue",
}
POSITIVE_ATTITUDE_TERMS = ["支持", "点赞", "满意", "认可", "感谢", "欢迎", "肯定", "赞扬", "好事", "益处", "有益"]
INFERENTIAL_ATTITUDE_TERMS = ["抵触", "强烈反对", "质疑", "认可", "满意", "支持", "赞扬"]
OFFICIAL_POSITIVE_STAKEHOLDERS = [
    "政府部门",
    "监管部门",
    "住建部门",
    "教育部门",
    "卫健部门",
    "医保局",
    "市场监管部门",
    "人大代表",
    "政协委员",
]
MEDIA_STAKEHOLDERS = ["媒体", "评论"]


SYSTEM_PROMPT = """You are a strict evidence faithfulness verifier.
You must judge whether a candidate stakeholder-opinion-sentiment tuple is supported only by the provided evidence.
Do not use external knowledge.
Do not infer beyond the evidence.
Return strict JSON only."""


USER_PROMPT_TEMPLATE = """任务：
请判断下面的“主体—观点—情绪—依据”候选元组是否被给定 evidence 支持。

你只能使用下方 evidence 文本。
不能使用外部知识。
不能补充新的事实。
不能替候选元组重新创作观点。
如果证据只支持一部分，请标记为 partially_supported。
如果证据不支持主体、观点、情绪或依据，请标记为 unsupported 或 unclear。

特别规则：
1. 官方通报、政策发布、监管回应、调查处理、机制完善等治理行为，sentiment 默认应为 neutral。
2. 只有证据明确出现支持、满意、认可、感谢、点赞、肯定、赞扬、欢迎等态度表达时，才能支持 positive。
3. 媒体评论、人大建议、政协建议、部门政策倡议，一般不应直接视为 positive，除非证据中有明确正向态度词。
4. 如果 opinion 比 evidence 表达更强，例如证据只是“不同意补贴”，候选却写成“抵触政策”，应标记为 partially_supported 或 unsupported。
5. 如果 evidence_id 对应证据无法支持 rationale，应添加 rationale_not_supported。
6. 如果 sentiment 无法由证据支持，应添加 sentiment_not_supported。

候选元组：
event_id: {event_id}
tuple_id: {tuple_id}
stakeholder: {stakeholder}
opinion: {opinion}
sentiment: {sentiment}
rationale: {rationale}
event_chain_stage: {event_chain_stage}
candidate_confidence: {confidence}

规则预检 issue_flags:
{precheck_flags}

证据：
{evidence_blocks}

请输出严格 JSON：

{{
  "tuple_id": "{tuple_id}",
  "event_id": "{event_id}",
  "verification_label": "supported|partially_supported|unsupported|unclear",
  "verification_score": 0.0,
  "verification_rationale": "简要说明该元组是否被证据支持",
  "supported_claims": ["证据支持的部分"],
  "unsupported_claims": ["证据不支持或过度推断的部分"],
  "evidence_quotes": ["从证据中摘取的关键短句"],
  "issue_flags": ["no_issue"]
}}

重要：
只输出一个 JSON 对象。
不要输出 Markdown。
不要输出 ```json。
不要输出解释性文字。
第一个字符必须是 {{，最后一个字符必须是 }}。"""


@dataclass
class VerificationParseResult:
    row: dict[str, Any] | None
    parse_success: bool
    parse_error: str | None = None


class FaithfulnessVerifier:
    def __init__(
        self,
        *,
        llm_client: Any | None,
        model_name: str,
        verifier_prompt_version: str = VERIFIER_PROMPT_VERSION,
    ):
        self.llm_client = llm_client
        self.model_name = model_name
        self.verifier_prompt_version = verifier_prompt_version

    def build_prompt(
        self,
        *,
        candidate: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        precheck_flags: list[str] | None = None,
    ) -> tuple[str, str]:
        user_prompt = USER_PROMPT_TEMPLATE.format(
            event_id=candidate.get("event_id", ""),
            tuple_id=candidate.get("tuple_id", ""),
            stakeholder=candidate.get("stakeholder", ""),
            opinion=candidate.get("opinion", ""),
            sentiment=candidate.get("sentiment", ""),
            rationale=candidate.get("rationale", ""),
            event_chain_stage=candidate.get("event_chain_stage", ""),
            confidence=candidate.get("confidence", candidate.get("candidate_confidence", "")),
            precheck_flags=json.dumps(normalize_issue_flags(precheck_flags or []), ensure_ascii=False),
            evidence_blocks=format_evidence_blocks(evidence_items),
        )
        return SYSTEM_PROMPT, user_prompt

    def verify_tuple(
        self,
        *,
        candidate: dict[str, Any],
        evidence_by_id: dict[str, dict[str, Any]],
        chain_stages_by_event: dict[str, set[str]] | None = None,
        dry_run: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        tuple_id = str(candidate.get("tuple_id", ""))
        event_id = str(candidate.get("event_id", ""))
        evidence_items, missing_ids = resolve_candidate_evidence(candidate, evidence_by_id)
        precheck_flags = rule_precheck(
            candidate=candidate,
            evidence_items=evidence_items,
            missing_evidence_ids=missing_ids,
            chain_stages_by_event=chain_stages_by_event or {},
        )
        system_prompt, user_prompt = self.build_prompt(
            candidate=candidate,
            evidence_items=evidence_items,
            precheck_flags=precheck_flags,
        )
        request_summary = {
            "num_evidence_ids": len(candidate.get("evidence_ids", []) or []),
            "num_evidence_found": len(evidence_items),
            "missing_evidence_ids": missing_ids,
            "prompt_chars": len(system_prompt) + len(user_prompt),
            "api_calls_made": 0,
            "json_mode": True,
        }
        if dry_run:
            preview = user_prompt[:2500]
            safe_console_print(f"\n--- verifier prompt preview: {tuple_id} ---\n{preview}\n--- end verifier prompt preview: {tuple_id} ---\n")
            row = fallback_verification_row(
                candidate,
                label="unclear" if evidence_items else "unsupported",
                score=0.0,
                rationale="dry-run preview only; LLM verification was not called.",
                issue_flags=precheck_flags,
                model_name=self.model_name,
            )
            return row, raw_record(
                tuple_id=tuple_id,
                event_id=event_id,
                model_name=self.model_name,
                request_summary=request_summary,
                raw_response="",
                parse_success=True,
                parse_error=None,
                dry_run=True,
            )
        if not evidence_items:
            row = fallback_verification_row(
                candidate,
                label="unsupported",
                score=0.0,
                rationale="No referenced evidence text was found for this tuple.",
                issue_flags=precheck_flags or ["missing_evidence"],
                model_name=self.model_name,
            )
            return row, raw_record(
                tuple_id=tuple_id,
                event_id=event_id,
                model_name=self.model_name,
                request_summary=request_summary,
                raw_response="",
                parse_success=True,
                parse_error=None,
            )
        if self.llm_client is None:
            raise RuntimeError("llm_client is required unless dry_run=True or all evidence is missing")

        response = self.llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
        )
        request_summary["api_calls_made"] = 1
        parsed = parse_verifier_response(
            response,
            candidate=candidate,
            model_name=self.model_name,
            verifier_prompt_version=self.verifier_prompt_version,
            raw_response_id=getattr(response, "response_id", ""),
            precheck_flags=precheck_flags,
        )
        raw_text = normalize_raw_response(response)
        if parsed.row is None:
            row = fallback_verification_row(
                candidate,
                label="unclear",
                score=0.0,
                rationale=f"Verifier response could not be parsed: {parsed.parse_error}",
                issue_flags=precheck_flags or ["weak_evidence"],
                raw_response_id=getattr(response, "response_id", ""),
                model_name=self.model_name,
            )
        else:
            row = parsed.row
        return row, raw_record(
            tuple_id=tuple_id,
            event_id=event_id,
            model_name=self.model_name,
            request_summary=request_summary,
            raw_response=raw_text,
            parse_success=parsed.parse_success,
            parse_error=parsed.parse_error,
        )


def run_faithfulness_verification(
    *,
    candidates: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    llm_client: Any | None,
    model_name: str,
    output_dir: str | Path,
    tuple_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    max_tuples: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = select_candidate_tuples(candidates, tuple_ids=tuple_ids, event_ids=event_ids, max_tuples=max_tuples)
    evidence_by_id = {str(row.get("evidence_id", "")): row for row in evidence_rows if row.get("evidence_id")}
    chain_stages = chain_stages_by_event(chains)
    verifier = FaithfulnessVerifier(llm_client=llm_client, model_name=model_name)

    verified_rows: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    api_failures = 0
    api_calls = 0
    parse_failed_tuples: list[str] = []
    missing_evidence_tuples: list[str] = []

    for candidate in selected:
        tuple_id = str(candidate.get("tuple_id", ""))
        try:
            row, record = verifier.verify_tuple(
                candidate=candidate,
                evidence_by_id=evidence_by_id,
                chain_stages_by_event=chain_stages,
                dry_run=dry_run,
            )
            verified_rows.append(row)
            raw_records.append(record)
            api_calls += int(record.get("request_summary", {}).get("api_calls_made", 0) or 0)
            if record.get("parse_success") is False:
                parse_failed_tuples.append(tuple_id)
            if "missing_evidence" in row.get("issue_flags", []):
                missing_evidence_tuples.append(tuple_id)
        except Exception as exc:
            api_failures += 1
            row = fallback_verification_row(
                candidate,
                label="unclear",
                score=0.0,
                rationale=f"Verifier API failure: {exc}",
                issue_flags=["weak_evidence"],
            )
            verified_rows.append(row)
            raw_records.append(
                raw_record(
                    tuple_id=tuple_id,
                    event_id=str(candidate.get("event_id", "")),
                    model_name=model_name,
                    request_summary={"api_calls_made": 1},
                    raw_response="",
                    parse_success=False,
                    parse_error=str(exc),
                )
            )

    verified_path = output_dir / "verified_soa_tuples.jsonl"
    raw_path = output_dir / "raw_verifier_responses.jsonl"
    table_path = output_dir / "verifier_table.csv"
    summary_path = output_dir / "verifier_summary.json"

    write_jsonl(verified_path, verified_rows)
    write_jsonl(raw_path, raw_records)
    write_verifier_table(table_path, verified_rows)
    summary = build_summary(
        candidates=selected,
        verified=verified_rows,
        api_calls=api_calls,
        api_failures=api_failures,
        parse_failed_tuples=parse_failed_tuples,
        missing_evidence_tuples=missing_evidence_tuples,
        output_path=str(verified_path),
        model_name=model_name,
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_verifier_response(
    raw_response: Any,
    *,
    candidate: dict[str, Any],
    model_name: str,
    verifier_prompt_version: str = VERIFIER_PROMPT_VERSION,
    raw_response_id: str = "",
    precheck_flags: list[str] | None = None,
) -> VerificationParseResult:
    text = normalize_raw_response(raw_response)
    if not text.strip():
        return VerificationParseResult(None, False, "empty_llm_content")
    try:
        json_text = extract_json_object(text)
    except ValueError as exc:
        return VerificationParseResult(None, False, str(exc))
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return VerificationParseResult(None, False, "incomplete_or_malformed_json")
    if not isinstance(payload, dict):
        return VerificationParseResult(None, False, "response JSON must be an object")
    if str(payload.get("tuple_id", "")) != str(candidate.get("tuple_id", "")):
        return VerificationParseResult(None, False, f"tuple_id mismatch: {payload.get('tuple_id')}")
    if str(payload.get("event_id", "")) != str(candidate.get("event_id", "")):
        return VerificationParseResult(None, False, f"event_id mismatch: {payload.get('event_id')}")
    label = str(payload.get("verification_label", "")).strip()
    if label not in ALLOWED_LABELS:
        return VerificationParseResult(None, False, f"invalid verification_label: {label}")
    score = clamp_float(payload.get("verification_score", 0.0))
    flags = normalize_issue_flags(list(payload.get("issue_flags", []) or []) + list(precheck_flags or []))
    row = verified_tuple_row(
        candidate=candidate,
        verification_label=label,
        verification_score=score,
        verification_rationale=truncate_text(payload.get("verification_rationale", ""), 240),
        supported_claims=normalize_string_list(payload.get("supported_claims", []), max_items=8, max_chars=120),
        unsupported_claims=normalize_string_list(payload.get("unsupported_claims", []), max_items=8, max_chars=120),
        evidence_quotes=normalize_string_list(payload.get("evidence_quotes", []), max_items=6, max_chars=160),
        issue_flags=flags,
        model_name=model_name,
        verifier_prompt_version=verifier_prompt_version,
        raw_response_id=raw_response_id,
    )
    return VerificationParseResult(row, True, None)


def rule_precheck(
    *,
    candidate: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    missing_evidence_ids: list[str],
    chain_stages_by_event: dict[str, set[str]],
) -> list[str]:
    flags: list[str] = []
    evidence_text = "\n".join(str(item.get("text", "")) for item in evidence_items)
    stakeholder = str(candidate.get("stakeholder", ""))
    opinion = str(candidate.get("opinion", ""))
    rationale = str(candidate.get("rationale", ""))
    sentiment = str(candidate.get("sentiment", ""))
    if missing_evidence_ids:
        flags.append("missing_evidence")
    if any(not str(item.get("text", "")).strip() for item in evidence_items):
        flags.append("weak_evidence")
    if evidence_items and stakeholder and not stakeholder_supported_by_evidence(stakeholder, evidence_text, evidence_items):
        flags.append("stakeholder_not_supported")
    if evidence_items and rationale and not claim_supported_by_evidence(rationale, evidence_text):
        flags.append("rationale_not_supported")
    if sentiment == "positive" and not contains_any(evidence_text, POSITIVE_ATTITUDE_TERMS):
        if contains_any(stakeholder, MEDIA_STAKEHOLDERS):
            flags.append("media_comment_should_be_neutral")
        if contains_any(stakeholder, OFFICIAL_POSITIVE_STAKEHOLDERS):
            flags.append("official_action_should_be_neutral")
        if contains_any(stakeholder, MEDIA_STAKEHOLDERS + OFFICIAL_POSITIVE_STAKEHOLDERS):
            flags.append("sentiment_not_supported")
    if any(term in opinion for term in INFERENTIAL_ATTITUDE_TERMS) and not contains_any(evidence_text, INFERENTIAL_ATTITUDE_TERMS):
        flags.append("opinion_overgeneralized")
    event_id = str(candidate.get("event_id", ""))
    stage = str(candidate.get("event_chain_stage", ""))
    known_stages = chain_stages_by_event.get(event_id, set())
    if known_stages and stage and stage not in known_stages and stage != "unknown":
        flags.append("stage_mismatch")
    return normalize_issue_flags(flags)


def resolve_candidate_evidence(
    candidate: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    evidence_items: list[dict[str, Any]] = []
    missing: list[str] = []
    for evidence_id in normalize_string_list(candidate.get("evidence_ids", []), max_items=50, max_chars=80):
        row = evidence_by_id.get(evidence_id)
        if row is None:
            missing.append(evidence_id)
            continue
        evidence_items.append(row)
    return evidence_items, missing


def format_evidence_blocks(evidence_items: list[dict[str, Any]], *, max_chars: int = 1200) -> str:
    if not evidence_items:
        return "无可用 evidence。"
    blocks: list[str] = []
    for item in evidence_items:
        blocks.append(
            "\n".join(
                [
                    f"- evidence_id: {item.get('evidence_id')}",
                    f"  source: {item.get('source', '')}",
                    f"  domain: {item.get('domain', '')}",
                    f"  url: {item.get('url', '')}",
                    f"  title: {truncate_text(item.get('title', ''), 120)}",
                    f"  text: {truncate_text(item.get('text', ''), max_chars)}",
                ]
            )
        )
    return "\n".join(blocks)


def select_candidate_tuples(
    candidates: list[dict[str, Any]],
    *,
    tuple_ids: list[str] | None,
    event_ids: list[str] | None,
    max_tuples: int | None,
) -> list[dict[str, Any]]:
    selected = candidates
    if tuple_ids:
        wanted = set(tuple_ids)
        selected = [row for row in selected if str(row.get("tuple_id", "")) in wanted]
    if event_ids:
        wanted_events = set(event_ids)
        selected = [row for row in selected if str(row.get("event_id", "")) in wanted_events]
    if max_tuples is not None and max_tuples > 0:
        selected = selected[:max_tuples]
    return selected


def chain_stages_by_event(chains: list[dict[str, Any]]) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for chain in chains:
        event_id = str(chain.get("event_id", ""))
        stages = {
            str(stage.get("stage", ""))
            for stage in chain.get("stages", [])
            if isinstance(stage, dict) and stage.get("stage")
        }
        if event_id and stages:
            output[event_id] = stages
    return output


def verified_tuple_row(
    *,
    candidate: dict[str, Any],
    verification_label: str,
    verification_score: float,
    verification_rationale: str,
    supported_claims: list[str],
    unsupported_claims: list[str],
    evidence_quotes: list[str],
    issue_flags: list[str],
    model_name: str,
    verifier_prompt_version: str,
    raw_response_id: str,
) -> dict[str, Any]:
    return {
        "event_id": str(candidate.get("event_id", "")),
        "tuple_id": str(candidate.get("tuple_id", "")),
        "stakeholder": str(candidate.get("stakeholder", "")),
        "opinion": str(candidate.get("opinion", "")),
        "sentiment": str(candidate.get("sentiment", "")),
        "rationale": str(candidate.get("rationale", "")),
        "evidence_ids": list(candidate.get("evidence_ids", []) or []),
        "event_chain_stage": str(candidate.get("event_chain_stage", "")),
        "candidate_confidence": clamp_float(candidate.get("confidence", candidate.get("candidate_confidence", 0.0))),
        "verification_label": verification_label,
        "verification_score": clamp_float(verification_score),
        "verification_rationale": verification_rationale,
        "supported_claims": supported_claims,
        "unsupported_claims": unsupported_claims,
        "evidence_quotes": evidence_quotes,
        "issue_flags": normalize_issue_flags(issue_flags),
        "model_name": model_name,
        "verifier_prompt_version": verifier_prompt_version,
        "raw_response_id": raw_response_id,
        "created_at": now_iso(),
    }


def fallback_verification_row(
    candidate: dict[str, Any],
    *,
    label: str,
    score: float,
    rationale: str,
    issue_flags: list[str],
    raw_response_id: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    return verified_tuple_row(
        candidate=candidate,
        verification_label=label if label in ALLOWED_LABELS else "unclear",
        verification_score=score,
        verification_rationale=rationale,
        supported_claims=[],
        unsupported_claims=[rationale] if rationale else [],
        evidence_quotes=[],
        issue_flags=issue_flags,
        model_name=model_name,
        verifier_prompt_version=VERIFIER_PROMPT_VERSION,
        raw_response_id=raw_response_id,
    )


def build_summary(
    *,
    candidates: list[dict[str, Any]],
    verified: list[dict[str, Any]],
    api_calls: int,
    api_failures: int,
    parse_failed_tuples: list[str],
    missing_evidence_tuples: list[str],
    output_path: str,
    model_name: str,
) -> dict[str, Any]:
    label_counts = Counter(row.get("verification_label", "unclear") for row in verified)
    flag_counts = Counter(flag for row in verified for flag in row.get("issue_flags", []))
    scores = [float(row.get("verification_score", 0) or 0) for row in verified]
    total = len(verified) or 1
    return {
        "num_candidate_tuples": len(candidates),
        "num_verified_tuples": len(verified),
        "num_api_calls": api_calls,
        "num_api_failures": api_failures,
        "parse_failed_tuples": parse_failed_tuples,
        "missing_evidence_tuples": missing_evidence_tuples,
        "label_distribution": dict(label_counts),
        "issue_flag_distribution": dict(flag_counts),
        "avg_verification_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "supported_rate": round(label_counts.get("supported", 0) / total, 4),
        "partially_supported_rate": round(label_counts.get("partially_supported", 0) / total, 4),
        "unsupported_rate": round(label_counts.get("unsupported", 0) / total, 4),
        "unclear_rate": round(label_counts.get("unclear", 0) / total, 4),
        "output_path": output_path,
        "model_name": model_name,
        "verifier_prompt_version": VERIFIER_PROMPT_VERSION,
    }


def write_verifier_table(path: str | Path, rows: list[dict[str, Any]]) -> None:
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
        "candidate_confidence",
        "verification_label",
        "verification_score",
        "verification_rationale",
        "issue_flags",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["evidence_ids"] = "|".join(str(item) for item in row.get("evidence_ids", []))
            flat["issue_flags"] = "|".join(str(item) for item in row.get("issue_flags", []))
            writer.writerow(flat)


def raw_record(
    *,
    tuple_id: str,
    event_id: str,
    model_name: str,
    request_summary: dict[str, Any],
    raw_response: str,
    parse_success: bool,
    parse_error: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    record = {
        "tuple_id": tuple_id,
        "event_id": event_id,
        "model_name": model_name,
        "verifier_prompt_version": VERIFIER_PROMPT_VERSION,
        "request_summary": request_summary,
        "raw_response": raw_response,
        "parse_success": parse_success,
        "parse_error": parse_error,
    }
    if dry_run:
        record["dry_run"] = True
    return record


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


def normalize_issue_flags(flags: list[str]) -> list[str]:
    output: list[str] = []
    for flag in flags:
        value = str(flag).strip()
        if value in ALLOWED_ISSUE_FLAGS and value != "no_issue" and value not in output:
            output.append(value)
    return output or ["no_issue"]


def normalize_string_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value[:max_items]:
        text = truncate_text(item, max_chars)
        if text:
            output.append(text)
    return output


def meaningful_tokens(text: str) -> list[str]:
    clean = re.sub(r"[，。！？、；：,.!?;:\s]", "", text)
    if len(clean) <= 4:
        return [clean]
    tokens = [clean[idx : idx + 4] for idx in range(0, max(1, len(clean) - 3), 4)]
    tokens.extend(clean[idx : idx + 2] for idx in range(0, max(1, len(clean) - 1), 2))
    tokens.extend(match.group(0) for match in re.finditer(r"[\u4e00-\u9fff]{2,}", text))
    return tokens


def loose_contains(text: str, needle: str) -> bool:
    if not needle:
        return True
    if needle in text:
        return True
    if len(needle) >= 4 and needle[:4] in text:
        return True
    return any(token in text for token in meaningful_tokens(needle)[:2])


def contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def stakeholder_supported_by_evidence(stakeholder: str, evidence_text: str, evidence_items: list[dict[str, Any]]) -> bool:
    if loose_contains(evidence_text, stakeholder):
        return True
    aliases = stakeholder_aliases(stakeholder)
    if any(alias and alias in evidence_text for alias in aliases):
        return True
    source_text = "\n".join(
        str(item.get(key, ""))
        for item in evidence_items
        for key in ("source", "domain", "title", "url")
    )
    if contains_any(stakeholder, MEDIA_STAKEHOLDERS) and re.search(r"媒体|新闻|日报|晚报|时报|网|客户端|评论", source_text):
        return True
    return False


def stakeholder_aliases(stakeholder: str) -> list[str]:
    aliases: list[str] = []
    if "住建" in stakeholder:
        aliases.extend(["住房建设局", "住房城乡建设", "住房建设", "住建局"])
    if "教育" in stakeholder:
        aliases.extend(["教育厅", "教育局", "教育体育局", "教体局", "学校"])
    if "监管" in stakeholder:
        aliases.extend(["市场监管", "监督管理", "监管部门"])
    if "交通" in stakeholder:
        aliases.extend(["交通运输部", "交通部", "交通运输"])
    if "官方" in stakeholder or "政府" in stakeholder:
        aliases.extend(["官方", "通报", "政府", "部门", "局", "办事处"])
    if "调查组" in stakeholder:
        aliases.extend(["联合调查组", "调查组", "工作组"])
    if "学生" in stakeholder:
        aliases.extend(["学生", "同学", "来信人"])
    if "租户" in stakeholder:
        aliases.extend(["租户", "租客", "租房者"])
    if "房东" in stakeholder:
        aliases.extend(["房东", "业主", "房主"])
    if contains_any(stakeholder, MEDIA_STAKEHOLDERS):
        aliases.extend(["媒体", "评论", "日报", "新闻客户端", "人民财评"])
    return aliases


def claim_supported_by_evidence(claim: str, evidence_text: str) -> bool:
    if loose_contains(evidence_text, claim):
        return True
    tokens = meaningful_tokens(claim)
    if not tokens:
        return True
    matches = sum(1 for token in tokens if token and token in evidence_text)
    return matches >= min(2, len(tokens))


def truncate_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


def clamp_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_console_print(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    sys.stdout.flush()
