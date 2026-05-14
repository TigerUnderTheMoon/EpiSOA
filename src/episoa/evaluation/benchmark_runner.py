"""LLM-based benchmark task runners shared across eval scripts."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from episoa.llm.client import OpenAICompatibleClient


# ---------------------------------------------------------------------------
# Prompt templates (Chinese, aligned with existing EpiSOA prompt style)
# These string constants serve as fallback defaults.  The runner functions
# will prefer loading identically-named .md files from a prompt directory.
# ---------------------------------------------------------------------------

TUPLE_IDENTIFICATION_SYSTEM = """你是一个中文公共事件利益相关方观点归因专家。你需要根据给定的事件信息和候选证据，识别所有利益相关方及其观点。

输出严格的 JSON，格式如下：
{"tuples": [{"stakeholder": "利益相关方名称", "opinion": "具体观点描述", "sentiment": "positive/negative/mixed", "evidence_ids": ["ev-xxxxx", ...], "rationale": "归因依据"}]}

规则：
1. stakeholder 必须是具体群体或个人，不能是抽象概念
2. opinion 必须是可以从证据中直接验证的具体观点，不能是推测
3. sentiment 三选一：positive（支持/赞同/满意）、negative（反对/批评/不满）、mixed（混合/矛盾）
4. evidence_ids 只能从候选证据中选取，每项至少 1 条证据支撑
5. 每个事件至少识别 3 个利益相关方观点
6. rationale 简要说明为什么这些证据支撑了该观点"""

TUPLE_IDENTIFICATION_USER = """事件：{event_name}
描述：{event_description}
时间：{time_window}
地点：{location}

候选证据：
{evidence_texts}

请识别所有利益相关方及其观点，输出 JSON。"""

EVIDENCE_SUPPORT_SYSTEM = """你是一个中文公共事件证据支撑度判定专家。你需要判断一条证据是否支撑给定的利益相关方观点。

输出严格的 JSON，格式如下：
{"support_label": "supported/not_enough_info/partially_supported", "reason": "判定理由"}

规则：
1. supported: 证据明确支撑该利益相关方和观点
2. partially_supported: 证据部分支撑，但不完整
3. not_enough_info: 证据不足以支撑该观点，或证据不相关
4. 判定依据必须是证据文本的实际内容，不能推测"""

EVIDENCE_SUPPORT_USER = """事件：{event_name}
利益相关方：{stakeholder}
观点：{opinion}
情感：{sentiment}

证据 ID：{evidence_id}
证据来源：{source_type}
证据内容：{evidence_text}

请判定该证据是否支撑上述观点，输出 JSON。"""

CHAIN_CONSTRUCTION_SYSTEM = """你是一个中文公共事件事件链构建专家。你需要根据事件信息和候选证据，构建事件演化链。

输出严格的 JSON，格式如下：
{"chains": [{"evidence_ids": ["ev-xxxxx", ...], "event_chain": ["阶段1描述", "阶段2描述", ...]}]}

规则：
1. 事件链覆盖 6 个生命周期阶段：trigger(触发)、diffusion(扩散)、conflict(冲突)、response(回应)、resolution(解决)、follow_up(后续)
2. 每条链由 3-5 个关键阶段节点组成
3. 每个阶段需从证据中找到支撑
4. evidence_ids 只能从候选证据中选取
5. 每条链的 evidence_ids 至少包含 3 条证据
6. 生成 2-3 条候选链覆盖不同的事件演化路径"""

CHAIN_CONSTRUCTION_USER = """事件：{event_name}
描述：{event_description}
时间：{time_window}
地点：{location}

候选证据：
{evidence_texts}

请构建事件演化链，输出 JSON。"""


# Mapping from constant name → prompt file name (relative to prompt_dir)
_PROMPT_FILE_MAP = {
    "TUPLE_IDENTIFICATION_SYSTEM": "benchmark_tuple_system.md",
    "TUPLE_IDENTIFICATION_USER": "benchmark_tuple_user.md",
    "EVIDENCE_SUPPORT_SYSTEM": "benchmark_evidence_system.md",
    "EVIDENCE_SUPPORT_USER": "benchmark_evidence_user.md",
    "CHAIN_CONSTRUCTION_SYSTEM": "benchmark_chain_system.md",
    "CHAIN_CONSTRUCTION_USER": "benchmark_chain_user.md",
}


def _load_prompt(name: str, prompt_dir: str | None) -> str:
    """Load a prompt from file with fallback to the in-module string constant."""
    if prompt_dir:
        file_name = _PROMPT_FILE_MAP.get(name)
        if file_name:
            path = Path(prompt_dir) / file_name
            if path.exists():
                return path.read_text(encoding="utf-8")
    # Fallback to module-level string constant
    return globals().get(name, "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response that may contain markdown fences."""
    text = (text or "").strip()
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _format_evidence_candidates(ev_list: list[dict], max_chars: int = 400, max_items: int = 15) -> str:
    lines = []
    for ev in ev_list[:max_items]:
        text = ev.get("text", "")[:max_chars]
        lines.append(f"[{ev['evidence_id']}] ({ev.get('source_type', '?')}) {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task runners
# ---------------------------------------------------------------------------

def run_tuple_identification(
    client: OpenAICompatibleClient, task_rows: list[dict], model_name: str,
    prompt_dir: str | None = None,
) -> tuple[list[dict], dict]:
    from episoa.evaluation.benchmark_metrics import eval_tuple_identification

    system_prompt = _load_prompt("TUPLE_IDENTIFICATION_SYSTEM", prompt_dir)
    user_template = _load_prompt("TUPLE_IDENTIFICATION_USER", prompt_dir)

    predictions = []
    for row in task_rows:
        inp = row["input"]
        event = inp["event"]
        evidence_texts = _format_evidence_candidates(inp["evidence_candidates"])

        user_prompt = user_template.format(
            event_name=event.get("event_name", ""),
            event_description=event.get("event_description", ""),
            time_window=json.dumps(event.get("time_window", {}), ensure_ascii=False),
            location=json.dumps(event.get("location", {}), ensure_ascii=False),
            evidence_texts=evidence_texts,
        )

        try:
            resp = client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            parsed = _extract_json(resp.content)
        except Exception as exc:
            parsed = {"tuples": [], "_error": str(exc)}

        predictions.append({
            "task_id": row["task_id"],
            "event_id": row["event_id"],
            "task_type": "tuple_identification",
            "model_name": model_name,
            "input": inp,
            "output": row["output"],
            "prediction": parsed,
        })
        time.sleep(0.1)

    metrics = eval_tuple_identification(predictions)
    return predictions, metrics


def run_evidence_support(
    client: OpenAICompatibleClient, task_rows: list[dict], model_name: str,
    prompt_dir: str | None = None,
) -> tuple[list[dict], dict]:
    from episoa.evaluation.benchmark_metrics import eval_evidence_support

    system_prompt = _load_prompt("EVIDENCE_SUPPORT_SYSTEM", prompt_dir)
    user_template = _load_prompt("EVIDENCE_SUPPORT_USER", prompt_dir)

    predictions = []
    for row in task_rows:
        inp = row["input"]
        event = inp["event"]
        tup = inp["tuple_claim"]
        evidence = inp["evidence"]

        user_prompt = user_template.format(
            event_name=event.get("event_name", ""),
            stakeholder=tup.get("stakeholder", ""),
            opinion=tup.get("opinion", ""),
            sentiment=tup.get("sentiment", ""),
            evidence_id=evidence.get("evidence_id", ""),
            source_type=evidence.get("source_type", ""),
            evidence_text=evidence.get("text", "")[:1500],
        )

        try:
            resp = client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            parsed = _extract_json(resp.content)
        except Exception as exc:
            parsed = {"support_label": "not_enough_info", "_error": str(exc)}

        predictions.append({
            "task_id": row["task_id"],
            "event_id": row["event_id"],
            "candidate_id": row["candidate_id"],
            "evidence_id": row["evidence_id"],
            "task_type": "evidence_support_classification",
            "model_name": model_name,
            "prediction": parsed,
            "gold_label": row["output"]["support_label"],
            "sample_type": row.get("metadata", {}).get("sample_type", "unknown"),
        })
        time.sleep(0.1)

    metrics = eval_evidence_support(predictions)
    return predictions, metrics


def run_chain_construction(
    client: OpenAICompatibleClient, task_rows: list[dict], model_name: str,
    prompt_dir: str | None = None,
) -> tuple[list[dict], dict]:
    from episoa.evaluation.benchmark_metrics import eval_chain_construction

    system_prompt = _load_prompt("CHAIN_CONSTRUCTION_SYSTEM", prompt_dir)
    user_template = _load_prompt("CHAIN_CONSTRUCTION_USER", prompt_dir)

    predictions = []
    for row in task_rows:
        inp = row["input"]
        event = inp["event"]
        evidence_texts = _format_evidence_candidates(inp["evidence_candidates"])

        user_prompt = user_template.format(
            event_name=event.get("event_name", ""),
            event_description=event.get("event_description", ""),
            time_window=json.dumps(event.get("time_window", {}), ensure_ascii=False),
            location=json.dumps(event.get("location", {}), ensure_ascii=False),
            evidence_texts=evidence_texts,
        )

        try:
            resp = client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            parsed = _extract_json(resp.content)
        except Exception as exc:
            parsed = {"chains": [], "_error": str(exc)}

        predictions.append({
            "task_id": row["task_id"],
            "event_id": row["event_id"],
            "task_type": "chain_construction",
            "model_name": model_name,
            "input": inp,
            "output": row["output"],
            "prediction": parsed,
        })
        time.sleep(0.1)

    metrics = eval_chain_construction(predictions)
    return predictions, metrics
