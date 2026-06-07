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
from episoa.llm.client import json_schema_response_format
from episoa.retrieval.evidence_selector import SELECTOR_MODES, select_evidence_for_prompt


PROMPT_VERSION = "schema_attribution_v3_stakeholder_canonical_json"
METHOD_VERSION = "soe_v2"
SOE_V3_METHOD_VERSION = "soe_v3"
ATTRIBUTION_MODE = "stakeholder_canonical"
MAX_TUPLES_PER_EVENT = 8
MAX_OPINION_CHARS = 150
MAX_RATIONALE_CHARS = 120
ALLOWED_SENTIMENT = {"positive", "negative", "neutral", "mixed"}
ALLOWED_STAGE = {"trigger", "diffusion", "conflict", "response", "resolution", "follow_up", "mixed", "unknown"}
ALLOWED_SUPPORT = {"candidate_supported", "candidate_partially_supported", "candidate_unclear"}
STAGE_PRIORITY = ["conflict", "response", "resolution", "trigger", "diffusion", "follow_up"]
MAX_STAKEHOLDER_CANDIDATES = 40
GENERIC_STAKEHOLDER_LABELS = {
    "项目",
    "事件",
    "报道",
    "媒体",
    "媒体报道",
    "新闻报道",
    "文章",
    "政府部门",
    "相关部门",
    "有关部门",
    "实施单位",
    "项目方",
    "居民/公众",
    "公众",
    "网友",
    "社会",
    "社会公众",
    "社会舆论",
    "居民",
    "市民",
    "群众",
    "大众",
    "民众",
    "老百姓",
    "社区居民",
    "公众/网友",
    "公众质疑者",
}
PSEUDO_STAKEHOLDER_TERMS = ("项目", "事件", "事故", "风波", "舆情", "报道", "新闻", "文章", "方案")
ISSUE_DESCRIPTOR_TERMS = ("安全", "治理", "处置", "争议", "问题", "抽成")
ACTOR_HINT_TERMS = (
    "政府",
    "局",
    "委",
    "办",
    "法院",
    "检察院",
    "公安",
    "医院",
    "学校",
    "公司",
    "企业",
    "集团",
    "物业",
    "业主",
    "居民",
    "住户",
    "村民",
    "公众",
    "网友",
    "家长",
    "学生",
    "患者",
    "专家",
    "律师",
    "开发商",
    "运营商",
    "街道",
    "社区",
    "村委",
    "党委",
    "监管",
    "消防",
    "商户",
    "平台",
    "食堂",
)
SPECIFIC_ACTOR_TERMS = (
    "政府",
    "局",
    "委",
    "办",
    "法院",
    "检察院",
    "公安",
    "医院",
    "学校",
    "公司",
    "集团",
    "物业",
    "街道",
    "社区",
    "村委",
    "党委",
    "协会",
)

SCHEMA_ATTRIBUTION_RESPONSE_FORMAT = json_schema_response_format(
    "schema_attribution_response",
    {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "tuples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stakeholder": {"type": "string"},
                        "opinion": {"type": "string"},
                        "sentiment": {"type": "string", "enum": sorted(ALLOWED_SENTIMENT)},
                        "rationale": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "event_chain_stage": {"type": "string", "enum": sorted(ALLOWED_STAGE)},
                        "support_status": {"type": "string", "enum": sorted(ALLOWED_SUPPORT)},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "stakeholder_cluster_id": {"type": "string"},
                        "stakeholder_aliases": {"type": "array", "items": {"type": "string"}},
                        "canonical_tuple": {"type": "boolean"},
                        "opinion_split_reason": {"type": "string"},
                        "stakeholder_candidate_match_status": {
                            "type": "string",
                            "enum": ["matched", "unmatched", "no_candidates"],
                        },
                        "stage_candidate_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "stakeholder",
                        "opinion",
                        "sentiment",
                        "rationale",
                        "evidence_ids",
                        "event_chain_stage",
                        "support_status",
                        "confidence",
                        "stakeholder_cluster_id",
                        "stakeholder_aliases",
                        "canonical_tuple",
                        "opinion_split_reason",
                        "stakeholder_candidate_match_status",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["event_id", "tuples"],
        "additionalProperties": False,
    },
)

STAGE_SOA_RESPONSE_FORMAT = json_schema_response_format(
    "stage_soa_extraction_response",
    {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "stage_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stage_candidate_id": {"type": "string"},
                        "stakeholder": {"type": "string"},
                        "opinion": {"type": "string"},
                        "sentiment": {"type": "string", "enum": sorted(ALLOWED_SENTIMENT)},
                        "event_chain_stage": {"type": "string", "enum": sorted(ALLOWED_STAGE)},
                        "rationale": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "evidence_spans": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "evidence_id": {"type": "string"},
                                    "char_start": {"type": "integer"},
                                    "char_end": {"type": "integer"},
                                    "text": {"type": "string"},
                                },
                                "required": ["evidence_id", "char_start", "char_end", "text"],
                                "additionalProperties": False,
                            },
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": [
                        "stage_candidate_id",
                        "stakeholder",
                        "opinion",
                        "sentiment",
                        "event_chain_stage",
                        "rationale",
                        "evidence_ids",
                        "evidence_spans",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["event_id", "stage_candidates"],
        "additionalProperties": False,
    },
)

SYSTEM_PROMPT = """You are an information extraction system for evidence-grounded stakeholder opinion attribution in public events.
You must extract stakeholder-opinion-sentiment-rationale tuples only from the provided evidence.
Do not use external knowledge.
Do not invent stakeholders, opinions, rationales, or evidence IDs.
Return strict JSON only.
If the evidence is insufficient, return an empty tuples list.
The first character must be { and the last character must be }."""


USER_PROMPT_TEMPLATE = """Task: Extract stakeholder-canonical SOA tuples for one public event.

Rules:
1. Use only the evidence listed below. Do not use external knowledge.
2. First identify distinct stakeholder clusters at event level. Merge aliases such as residents/villagers/local residents when they refer to the same actor.
3. For each evidence-supported distinct stakeholder cluster, output one canonical tuple by default.
4. If several evidence items support the same stakeholder and the same opinion/action, merge them into one tuple and include all supporting evidence_ids.
5. Output multiple tuples for the same stakeholder_cluster_id only when the stakeholder has semantically different opinions/actions. In that case, opinion_split_reason must explain the split.
6. Do not create tuples to reach a fixed count. There is no per-event target N.
7. Every tuple must cite at least one evidence_id shown below.
8. Prefer stakeholder names from stakeholder_candidates when they fit the evidence, but you may add an evidence-supported stakeholder missing from the list.
9. stakeholder must be an actor or affected group. Do not use project names, event names, media reports, articles, generic "government department", "relevant department", or "implementing unit" as stakeholders.
10. Use gold-style canonical stakeholder names: concrete institution/person/group when available, otherwise concise affected group labels. Prefer the stakeholder_candidates inventory as the canonical name list.
11. Do NOT merge different organizations, agencies, or distinct actor groups into generic labels like "居民/公众". Prefer specific names: "美心翡翠明庭小区业主" over "居民/公众", "三元里村党委及村集体" over "三元里村".
12. sentiment must be positive, negative, neutral, or mixed. Use mixed when the same stakeholder has both support/benefit and concern/opposition in the evidence. Do NOT use neutral when evidence shows both positive and negative sentiments — use mixed instead.
13. Official policy release, investigation, response, supervision, or corrective action is neutral unless the evidence explicitly states support/satisfaction/praise or criticism/blame.
14. opinion should be specific and detailed. Include the stakeholder's concrete action, stance, or reasoning — not just "expressed concern" or "responded". Target 50-150 characters when possible.
15. Return strict JSON only. Do not output Markdown.

event:
event_id: {event_id}
event_name: {event_name}
event_description: {event_description}
seed_keywords: {seed_keywords}
stakeholder_hints: {stakeholder_hints}

event_chain_summary:
chain_confidence: {chain_confidence}
missing_stages: {missing_stages}

evidence:
{stage_evidence_blocks}

stakeholder_candidates:
{stakeholder_candidates}

JSON schema:
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder_cluster_id": "stable cluster id within this event, e.g. stakeholder_001",
      "stakeholder": "canonical stakeholder name",
      "stakeholder_aliases": ["aliases merged into this stakeholder"],
      "opinion": "evidence-supported opinion or action, <=150 Chinese chars when possible",
      "sentiment": "positive|negative|neutral|mixed",
      "rationale": "short evidence-grounded rationale, <=120 Chinese chars when possible",
      "evidence_ids": ["only evidence_id values shown above"],
      "event_chain_stage": "trigger|diffusion|conflict|response|resolution|follow_up|mixed|unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0,
      "canonical_tuple": true,
      "opinion_split_reason": "",
      "stakeholder_candidate_match_status": "matched|unmatched|no_candidates"
    }}
  ]
}}"""


RETRY_USER_PROMPT_TEMPLATE = """Extract stakeholder-canonical SOA tuples from the evidence below.
Use one tuple per evidence-supported distinct stakeholder by default. Merge evidence_ids for the same stakeholder and same opinion/action. Do not output a fixed number of tuples.
Return one strict JSON object only.

event_id: {event_id}
event_name: {event_name}

evidence:
{stage_evidence_blocks}

stakeholder_candidates:
{stakeholder_candidates}

JSON schema:
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder_cluster_id": "stakeholder_001",
      "stakeholder": "canonical stakeholder",
      "stakeholder_aliases": [],
      "opinion": "evidence-supported opinion or action",
      "sentiment": "positive|negative|neutral|mixed",
      "rationale": "short evidence-grounded rationale",
      "evidence_ids": ["evidence_id shown above"],
      "event_chain_stage": "trigger|diffusion|conflict|response|resolution|follow_up|mixed|unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0,
      "canonical_tuple": true,
      "opinion_split_reason": "",
      "stakeholder_candidate_match_status": "matched|unmatched|no_candidates"
    }}
  ]
}}"""


NO_CHAIN_USER_PROMPT_TEMPLATE = """Task: Extract stakeholder-canonical SOA tuples from the event and evidence below.
Use only the provided evidence. Do not use external knowledge. Do not invent stakeholders, opinions, rationales, or evidence IDs.
Identify distinct stakeholder clusters, output one canonical tuple per evidence-supported stakeholder by default, and split the same stakeholder only for different opinions/actions with opinion_split_reason.
Do NOT merge different organizations, agencies, or distinct actor groups into generic labels like "居民/公众". Prefer specific names from the evidence.
Return strict JSON only.

event_id: {event_id}
event_name: {event_name}
event_description: {event_description}
seed_keywords: {seed_keywords}
stakeholder_hints: {stakeholder_hints}

evidence:
{stage_evidence_blocks}

stakeholder_candidates:
{stakeholder_candidates}

JSON schema:
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder_cluster_id": "stakeholder_001",
      "stakeholder": "canonical stakeholder name",
      "stakeholder_aliases": [],
      "opinion": "opinion supported by evidence",
      "sentiment": "positive|negative|neutral|mixed",
      "rationale": "short evidence-grounded rationale",
      "evidence_ids": ["evidence_id shown above"],
      "event_chain_stage": "unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0,
      "canonical_tuple": true,
      "opinion_split_reason": "",
      "stakeholder_candidate_match_status": "matched|unmatched|no_candidates"
    }}
  ]
}}"""


NO_CHAIN_RETRY_USER_PROMPT_TEMPLATE = """Extract stakeholder-canonical SOA tuples from the evidence below.
Return one strict JSON object only.

event_id: {event_id}
event_name: {event_name}

evidence:
{stage_evidence_blocks}

stakeholder_candidates:
{stakeholder_candidates}

JSON schema:
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder_cluster_id": "stakeholder_001",
      "stakeholder": "stakeholder",
      "stakeholder_aliases": [],
      "opinion": "opinion supported by evidence",
      "sentiment": "positive|negative|neutral|mixed",
      "rationale": "short evidence-grounded rationale",
      "evidence_ids": ["evidence_id shown above"],
      "event_chain_stage": "unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0,
      "canonical_tuple": true,
      "opinion_split_reason": "",
      "stakeholder_candidate_match_status": "matched|unmatched|no_candidates"
    }}
  ]
}}"""


STAGE_EXTRACTION_USER_PROMPT_TEMPLATE = """Task: Extract stage-level SOA candidates for one public event.
Use only the evidence below. Return strict JSON only.

Rules:
1. Extract candidates at evidence/stage level; do not merge stakeholders across stages.
2. Every candidate must cite evidence_id values shown below.
3. stakeholder must be an actor or affected group, not a project/event/media-report title or generic "government department/relevant department/implementing unit" label.
4. Keep opinion and rationale concise but complete enough to preserve the stakeholder's core stance/action.
5. If no stage-level stakeholder opinion/action is supported, return an empty stage_candidates list.
6. Do NOT use generic labels like "居民/公众" as stakeholder when a more specific actor name is available in the evidence. Prefer "美心翡翠明庭小区业主" over "居民/公众".
7. opinion should include the stakeholder's specific action, stance, or causal reasoning — not just "expressed concern" or "responded". Target 50-150 characters when possible.

event:
event_id: {event_id}
event_name: {event_name}
event_description: {event_description}
stakeholder_hints: {stakeholder_hints}

evidence:
{stage_evidence_blocks}

stakeholder_candidates:
{stakeholder_candidates}

JSON schema:
{{
  "event_id": "{event_id}",
  "stage_candidates": [
    {{
      "stage_candidate_id": "{event_id}_STAGE_001",
      "stakeholder": "evidence-supported stakeholder",
      "opinion": "evidence-supported opinion or action",
      "sentiment": "positive|negative|neutral|mixed",
      "event_chain_stage": "trigger|diffusion|conflict|response|resolution|follow_up|mixed|unknown",
      "rationale": "short evidence-grounded rationale",
      "evidence_ids": ["evidence_id shown above"],
      "evidence_spans": [{{"evidence_id": "ev-id", "char_start": 0, "char_end": 0, "text": "supporting quote"}}],
      "confidence": 0.0
    }}
  ]
}}"""


CANONICAL_MERGE_USER_PROMPT_TEMPLATE = """Task: Merge stage-level SOA candidates into event-level stakeholder-canonical SOA tuples.
Use only the stage_candidates and evidence below. Return strict JSON only.

Rules:
1. Merge aliases that refer to the same stakeholder within this event.
2. Output one canonical tuple per distinct stakeholder by default.
3. Split the same stakeholder only when stage_candidates show different opinions/actions; explain with opinion_split_reason.
4. Keep all supporting evidence_ids and preserve relevant stage_candidate_ids.
5. Do not invent stakeholders, opinions, evidence IDs, or stage_candidate_ids.
6. Final stakeholder must be an actor or affected group, not a project/event/media-report title or generic "government department/relevant department/implementing unit" label.
7. Use stakeholder_candidates as the canonical event-level inventory whenever a candidate fits the evidence.
8. Do NOT merge stakeholders from different organizations, agencies, or distinct actor groups into a generic label like "居民/公众" unless the evidence explicitly presents them as a unified bloc. Prefer specific entity names from the evidence over generic labels from stakeholder_candidates — for example, prefer "美心翡翠明庭小区业主" over "居民/公众", prefer "三元里村党委及村集体" over "三元里村".
9. When merging stage candidates with conflicting sentiments (e.g., one positive and one negative), use "mixed" instead of "neutral". Do NOT downgrade conflicting sentiments to neutral.
10. Each opinion should be detailed and specific. Include what the stakeholder DID or SAID, their concrete stance or demand, and any numbers/dates/policy names. BAD: "expressed concern". GOOD: "要求开发商公开检测报告并退房退款，认为精装房质量与宣传严重不符". Target 50-200 characters.

event:
event_id: {event_id}
event_name: {event_name}
event_description: {event_description}

stage_candidates:
{stage_candidates}

evidence:
{stage_evidence_blocks}

stakeholder_candidates:
{stakeholder_candidates}

JSON schema:
{{
  "event_id": "{event_id}",
  "tuples": [
    {{
      "stakeholder_cluster_id": "stakeholder_001",
      "stakeholder": "canonical stakeholder name",
      "stakeholder_aliases": ["aliases merged into this stakeholder"],
      "opinion": "merged evidence-supported opinion or action",
      "sentiment": "positive|negative|neutral|mixed",
      "rationale": "short evidence-grounded rationale",
      "evidence_ids": ["evidence_id shown above"],
      "event_chain_stage": "trigger|diffusion|conflict|response|resolution|follow_up|mixed|unknown",
      "support_status": "candidate_supported|candidate_partially_supported|candidate_unclear",
      "confidence": 0.0,
      "canonical_tuple": true,
      "opinion_split_reason": "",
      "stakeholder_candidate_match_status": "matched|unmatched|no_candidates",
      "stage_candidate_ids": ["{event_id}_STAGE_001"]
    }}
  ]
}}"""


@dataclass
class ParseResult:
    tuples: list[dict[str, Any]]
    parse_success: bool
    parse_error: str | None = None
    rejected_rows: list[dict[str, Any]] | None = None


class SchemaAttributor:
    def __init__(
        self,
        *,
        llm_client: Any | None,
        model_name: str,
        prompt_version: str = PROMPT_VERSION,
        max_tuples_per_event: int = MAX_TUPLES_PER_EVENT,
        method_version: str = METHOD_VERSION,
    ):
        self.llm_client = llm_client
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.max_tuples_per_event = max_tuples_per_event
        self.method_version = method_version

    def build_prompt(
        self,
        *,
        event: dict[str, Any],
        chain: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        hide_chain_in_prompt: bool = False,
    ) -> tuple[str, str]:
        stage_evidence_blocks = format_stage_evidence_blocks(
            evidence_items,
            hide_chain_fields=hide_chain_in_prompt,
        )
        if hide_chain_in_prompt:
            user_prompt = NO_CHAIN_USER_PROMPT_TEMPLATE.format(
                event_id=event.get("event_id", ""),
                event_name=event.get("event_name", ""),
                event_description=event.get("event_description", ""),
                seed_keywords=json.dumps(event.get("seed_keywords", []), ensure_ascii=False),
                stakeholder_hints=json.dumps(event.get("stakeholder_hints", []), ensure_ascii=False),
                stage_evidence_blocks=stage_evidence_blocks,
                stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
            )
            user_prompt += self.method_constraint_text(stakeholder_candidates)
            return SYSTEM_PROMPT, user_prompt
        chain_confidence = chain.get("chain_confidence", 0)
        missing_stages = json.dumps(chain.get("missing_stages", []), ensure_ascii=False)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            event_id=event.get("event_id", ""),
            event_name=event.get("event_name", ""),
            event_description=event.get("event_description", ""),
            seed_keywords=json.dumps(event.get("seed_keywords", []), ensure_ascii=False),
            stakeholder_hints=json.dumps(event.get("stakeholder_hints", []), ensure_ascii=False),
            chain_confidence=chain_confidence,
            missing_stages=missing_stages,
            stage_evidence_blocks=stage_evidence_blocks,
            stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
        )
        user_prompt += self.method_constraint_text(stakeholder_candidates)
        return SYSTEM_PROMPT, user_prompt

    def method_constraint_text(self, stakeholder_candidates: list[str]) -> str:
        return (
            "\n\nMethod constraints:\n"
            f"- method_version: {self.method_version}\n"
            f"- attribution_mode: {ATTRIBUTION_MODE}\n"
            "- There is no fixed per-event tuple target.\n"
            "- Use only evidence_id values shown above.\n"
            "- Prefer stakeholder names from the stakeholder_candidates list when present.\n"
            "- Stakeholder names must be actors or affected groups, not project/event/media-report titles.\n"
            "- Do not use generic labels such as government department, relevant department, implementing unit, media report, project, or event.\n"
            "- Use concise gold-style canonical stakeholder names and merge aliases within the event.\n"
            "- Emit multiple tuples for the same stakeholder only when the opinion/action differs.\n"
            f"- stakeholder_candidate_count: {len(stakeholder_candidates)}\n"
        )

    def build_retry_prompt(
        self,
        *,
        event: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        hide_chain_in_prompt: bool = False,
    ) -> tuple[str, str]:
        stage_evidence_blocks = format_stage_evidence_blocks(
            evidence_items,
            max_excerpt_chars=220,
            hide_chain_fields=hide_chain_in_prompt,
        )
        if hide_chain_in_prompt:
            return SYSTEM_PROMPT, NO_CHAIN_RETRY_USER_PROMPT_TEMPLATE.format(
                event_id=event.get("event_id", ""),
                event_name=event.get("event_name", ""),
                stage_evidence_blocks=stage_evidence_blocks,
                stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
            )
        return SYSTEM_PROMPT, RETRY_USER_PROMPT_TEMPLATE.format(
            event_id=event.get("event_id", ""),
            event_name=event.get("event_name", ""),
            stage_evidence_blocks=stage_evidence_blocks,
            stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
        )

    def attribute_event(
        self,
        *,
        event: dict[str, Any],
        chain: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        selection_metadata: dict[str, Any] | None = None,
        dry_run: bool = False,
        hide_chain_in_prompt: bool = False,
        skip_chain_ranking: bool = False,
        enforce_candidate_constraints: bool = False,
        use_stage_attribution: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if use_stage_attribution:
            return self.attribute_event_two_pass(
                event=event,
                chain=chain,
                evidence_items=evidence_items,
                stakeholder_candidates=stakeholder_candidates,
                selection_metadata=selection_metadata,
                dry_run=dry_run,
                hide_chain_in_prompt=hide_chain_in_prompt,
                skip_chain_ranking=skip_chain_ranking,
                enforce_candidate_constraints=enforce_candidate_constraints,
            )
        system_prompt, user_prompt = self.build_prompt(
            event=event,
            chain=chain,
            evidence_items=evidence_items,
            stakeholder_candidates=stakeholder_candidates,
            hide_chain_in_prompt=hide_chain_in_prompt,
        )
        event_id = str(event.get("event_id", ""))
        selected_eids = [str(item.get("evidence_id", "")) for item in evidence_items if item.get("evidence_id")]
        request_summary = {
            "method_version": self.method_version,
            "attribution_mode": ATTRIBUTION_MODE,
            "num_evidence": len(evidence_items),
            "chain_confidence": chain.get("chain_confidence", 0),
            "prompt_chars": len(system_prompt) + len(user_prompt),
            "api_calls_made": 0,
            "json_mode": True,
            "selected_evidence_ids": selected_eids,
            "stakeholder_candidates": stakeholder_candidates,
            "stakeholder_candidate_count": len(stakeholder_candidates),
            "hide_chain_in_prompt": hide_chain_in_prompt,
            "skip_chain_ranking": skip_chain_ranking,
        }
        if selection_metadata:
            request_summary.update(selection_metadata)
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
        evidence_context_by_id = {str(item["evidence_id"]): item for item in evidence_items if item.get("evidence_id")}
        response = self.llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=SCHEMA_ATTRIBUTION_RESPONSE_FORMAT,
        )
        request_summary["api_calls_made"] = 1
        parsed = self._parse_llm_response(
            response,
            event_id,
            allowed_evidence_ids,
            stakeholder_candidates=stakeholder_candidates,
            evidence_context_by_id=evidence_context_by_id,
        )
        raw_response_text = normalize_raw_response(response)
        raw_response_id = getattr(response, "response_id", "")

        retryable_errors = {"empty_llm_content", "incomplete_or_malformed_json"}
        if parsed.parse_error in retryable_errors:
            retry_system_prompt, retry_user_prompt = self.build_retry_prompt(
                event=event,
                evidence_items=evidence_items,
                stakeholder_candidates=stakeholder_candidates,
                hide_chain_in_prompt=hide_chain_in_prompt,
            )
            retry_response = self.llm_client.chat(
                system_prompt=retry_system_prompt,
                user_prompt=retry_user_prompt,
                response_format=SCHEMA_ATTRIBUTION_RESPONSE_FORMAT,
            )
            request_summary["api_calls_made"] = 2
            if parsed.parse_error == "empty_llm_content":
                request_summary["retried_after_empty_content"] = True
            else:
                request_summary["retried_after_malformed_json"] = True
            parsed = self._parse_llm_response(
                retry_response,
                event_id,
                allowed_evidence_ids,
                stakeholder_candidates=stakeholder_candidates,
                evidence_context_by_id=evidence_context_by_id,
            )
            raw_response_text = normalize_raw_response(retry_response)
            raw_response_id = getattr(retry_response, "response_id", "")

        parsed_tuples, canonical_diagnostics = canonicalize_tuple_rows(
            parsed.tuples,
            event=event,
            stakeholder_candidates=stakeholder_candidates,
            evidence_items=evidence_items,
        )
        parsed.tuples = parsed_tuples
        request_summary["parsed_tuple_count"] = len(parsed.tuples)
        request_summary["rejected_tuple_count"] = len(parsed.rejected_rows or [])
        request_summary["canonicalization"] = {
            key: value
            for key, value in canonical_diagnostics.items()
            if key != "canonicalization_map"
        }
        request_summary["supplemented_stakeholders"] = sorted(
            {
                str(row.get("stakeholder", ""))
                for row in parsed.tuples
                if row.get("stakeholder_candidate_match_status") == "unmatched"
            }
        )
        return parsed.tuples, raw_record(
            event_id=event_id,
            model_name=self.model_name,
            request_summary=request_summary,
            raw_response=raw_response_text,
            parse_success=parsed.parse_success,
            parse_error=parsed.parse_error,
            parse_diagnostics={
                "rejected_rows": parsed.rejected_rows or [],
                "canonicalization_map": canonical_diagnostics.get("canonicalization_map", []),
            },
        )

    def build_stage_extraction_prompt(
        self,
        *,
        event: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        hide_chain_in_prompt: bool = False,
    ) -> tuple[str, str]:
        return SYSTEM_PROMPT, STAGE_EXTRACTION_USER_PROMPT_TEMPLATE.format(
            event_id=event.get("event_id", ""),
            event_name=event.get("event_name", ""),
            event_description=event.get("event_description", ""),
            stakeholder_hints=json.dumps(event.get("stakeholder_hints", []), ensure_ascii=False),
            stage_evidence_blocks=format_stage_evidence_blocks(
                evidence_items,
                hide_chain_fields=hide_chain_in_prompt,
            ),
            stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
        )

    def build_canonical_merge_prompt(
        self,
        *,
        event: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stage_candidates: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        hide_chain_in_prompt: bool = False,
    ) -> tuple[str, str]:
        return SYSTEM_PROMPT, CANONICAL_MERGE_USER_PROMPT_TEMPLATE.format(
            event_id=event.get("event_id", ""),
            event_name=event.get("event_name", ""),
            event_description=event.get("event_description", ""),
            stage_candidates=json.dumps(stage_candidates, ensure_ascii=False, indent=2),
            stage_evidence_blocks=format_stage_evidence_blocks(
                evidence_items,
                max_excerpt_chars=300,
                hide_chain_fields=hide_chain_in_prompt,
            ),
            stakeholder_candidates=json.dumps(stakeholder_candidates, ensure_ascii=False),
        )

    def attribute_event_two_pass(
        self,
        *,
        event: dict[str, Any],
        chain: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        selection_metadata: dict[str, Any] | None = None,
        dry_run: bool = False,
        hide_chain_in_prompt: bool = False,
        skip_chain_ranking: bool = False,
        enforce_candidate_constraints: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        event_id = str(event.get("event_id", ""))
        selected_eids = [str(item.get("evidence_id", "")) for item in evidence_items if item.get("evidence_id")]
        stage_system, stage_user = self.build_stage_extraction_prompt(
            event=event,
            evidence_items=evidence_items,
            stakeholder_candidates=stakeholder_candidates,
            hide_chain_in_prompt=hide_chain_in_prompt,
        )
        request_summary = {
            "method_version": self.method_version,
            "attribution_mode": ATTRIBUTION_MODE,
            "attribution_pass": "soe_v3_two_pass",
            "num_evidence": len(evidence_items),
            "chain_confidence": chain.get("chain_confidence", 0),
            "prompt_chars": len(stage_system) + len(stage_user),
            "stage_prompt_chars": len(stage_system) + len(stage_user),
            "api_calls_made": 0,
            "json_mode": True,
            "selected_evidence_ids": selected_eids,
            "stakeholder_candidates": stakeholder_candidates,
            "stakeholder_candidate_count": len(stakeholder_candidates),
            "hide_chain_in_prompt": hide_chain_in_prompt,
            "skip_chain_ranking": skip_chain_ranking,
        }
        if selection_metadata:
            request_summary.update(selection_metadata)
            request_summary["attribution_pass"] = "soe_v3_two_pass"
        if dry_run:
            preview = stage_user[:2500]
            safe_console_print(f"\n--- stage extraction prompt preview: {event_id} ---\n{preview}\n--- end stage extraction prompt: {event_id} ---\n")
            return [], raw_record(
                event_id=event_id,
                model_name=self.model_name,
                request_summary=request_summary,
                raw_response="",
                parse_success=True,
                parse_error=None,
                parse_diagnostics={"stage_candidates": []},
                dry_run=True,
            )
        if self.llm_client is None:
            raise RuntimeError("llm_client is required unless dry_run=True")

        allowed_evidence_ids = {str(item["evidence_id"]) for item in evidence_items if item.get("evidence_id")}
        evidence_context_by_id = {str(item["evidence_id"]): item for item in evidence_items if item.get("evidence_id")}
        retryable_errors = {"empty_llm_content", "incomplete_or_malformed_json"}

        stage_response = self.llm_client.chat(
            system_prompt=stage_system,
            user_prompt=stage_user,
            response_format=STAGE_SOA_RESPONSE_FORMAT,
        )
        request_summary["api_calls_made"] = 1
        stage_parsed = parse_stage_response(
            stage_response,
            event_id=event_id,
            allowed_evidence_ids=allowed_evidence_ids,
            evidence_context_by_id=evidence_context_by_id,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response_id=getattr(stage_response, "response_id", ""),
        )
        stage_raw = normalize_raw_response(stage_response)
        if stage_parsed.parse_error in retryable_errors:
            stage_response = self.llm_client.chat(
                system_prompt=stage_system,
                user_prompt=stage_user,
                response_format=STAGE_SOA_RESPONSE_FORMAT,
            )
            request_summary["api_calls_made"] = 2
            request_summary["stage_extract_retried"] = True
            stage_parsed = parse_stage_response(
                stage_response,
                event_id=event_id,
                allowed_evidence_ids=allowed_evidence_ids,
                evidence_context_by_id=evidence_context_by_id,
                model_name=self.model_name,
                prompt_version=self.prompt_version,
                raw_response_id=getattr(stage_response, "response_id", ""),
            )
            stage_raw = normalize_raw_response(stage_response)

        if not stage_parsed.parse_success:
            return self._fallback_to_legacy_single_pass(
                event=event,
                chain=chain,
                evidence_items=evidence_items,
                stakeholder_candidates=stakeholder_candidates,
                selection_metadata=selection_metadata,
                dry_run=dry_run,
                hide_chain_in_prompt=hide_chain_in_prompt,
                skip_chain_ranking=skip_chain_ranking,
                enforce_candidate_constraints=enforce_candidate_constraints,
                prior_api_calls=int(request_summary["api_calls_made"]),
                fallback_reason=stage_parsed.parse_error or "stage_extract_failed",
                stage_candidates=[],
            )

        stage_tuples, stage_canonical_diagnostics = canonicalize_stage_candidate_rows(
            stage_parsed.tuples,
            event=event,
            stakeholder_candidates=stakeholder_candidates,
            evidence_items=evidence_items,
        )
        stage_parsed.tuples = stage_tuples
        request_summary["stage_candidate_count"] = len(stage_parsed.tuples)
        request_summary["stage_rejected_candidate_count"] = len(stage_parsed.rejected_rows or [])
        request_summary["stage_canonicalization"] = {
            key: value
            for key, value in stage_canonical_diagnostics.items()
            if key != "canonicalization_map"
        }
        if not stage_parsed.tuples:
            request_summary["parsed_tuple_count"] = 0
            return [], raw_record(
                event_id=event_id,
                model_name=self.model_name,
                request_summary=request_summary,
                raw_response=json.dumps({"stage_extract": stage_raw, "canonical_merge": ""}, ensure_ascii=False),
                parse_success=True,
                parse_error=None,
                parse_diagnostics={
                    "stage_candidates": [],
                    "stage_rejected_rows": stage_parsed.rejected_rows or [],
                    "rejected_rows": [],
                    "stage_canonicalization_map": stage_canonical_diagnostics.get("canonicalization_map", []),
                },
            )

        merge_system, merge_user = self.build_canonical_merge_prompt(
            event=event,
            evidence_items=evidence_items,
            stage_candidates=stage_parsed.tuples,
            stakeholder_candidates=stakeholder_candidates,
            hide_chain_in_prompt=hide_chain_in_prompt,
        )
        request_summary["prompt_chars"] += len(merge_system) + len(merge_user)
        request_summary["merge_prompt_chars"] = len(merge_system) + len(merge_user)
        merge_response = self.llm_client.chat(
            system_prompt=merge_system,
            user_prompt=merge_user,
            response_format=SCHEMA_ATTRIBUTION_RESPONSE_FORMAT,
        )
        request_summary["api_calls_made"] = int(request_summary["api_calls_made"]) + 1
        merge_parsed = self._parse_llm_response(
            merge_response,
            event_id,
            allowed_evidence_ids,
            stakeholder_candidates=stakeholder_candidates,
            evidence_context_by_id=evidence_context_by_id,
        )
        merge_raw = normalize_raw_response(merge_response)
        if merge_parsed.parse_error in retryable_errors:
            merge_response = self.llm_client.chat(
                system_prompt=merge_system,
                user_prompt=merge_user,
                response_format=SCHEMA_ATTRIBUTION_RESPONSE_FORMAT,
            )
            request_summary["api_calls_made"] = int(request_summary["api_calls_made"]) + 1
            request_summary["canonical_merge_retried"] = True
            merge_parsed = self._parse_llm_response(
                merge_response,
                event_id,
                allowed_evidence_ids,
                stakeholder_candidates=stakeholder_candidates,
                evidence_context_by_id=evidence_context_by_id,
            )
            merge_raw = normalize_raw_response(merge_response)

        if not merge_parsed.parse_success:
            return self._fallback_to_legacy_single_pass(
                event=event,
                chain=chain,
                evidence_items=evidence_items,
                stakeholder_candidates=stakeholder_candidates,
                selection_metadata=selection_metadata,
                dry_run=dry_run,
                hide_chain_in_prompt=hide_chain_in_prompt,
                skip_chain_ranking=skip_chain_ranking,
                enforce_candidate_constraints=enforce_candidate_constraints,
                prior_api_calls=int(request_summary["api_calls_made"]),
                fallback_reason=merge_parsed.parse_error or "canonical_merge_failed",
                stage_candidates=stage_parsed.tuples,
            )

        merge_tuples, merge_canonical_diagnostics = canonicalize_tuple_rows(
            merge_parsed.tuples,
            event=event,
            stakeholder_candidates=stakeholder_candidates,
            evidence_items=evidence_items,
            stage_candidates=stage_parsed.tuples,
        )
        merge_parsed.tuples = merge_tuples
        for row in merge_parsed.tuples:
            row["attribution_pass"] = "soe_v3_two_pass"
            if not row.get("stage_candidate_ids"):
                row["stage_candidate_ids"] = infer_stage_candidate_ids(row, stage_parsed.tuples)
            stage_spans = evidence_spans_from_stage_candidates(
                row.get("stage_candidate_ids", []),
                stage_parsed.tuples,
                row.get("evidence_ids", []),
            )
            if stage_spans:
                row["evidence_spans"] = stage_spans
        request_summary["parsed_tuple_count"] = len(merge_parsed.tuples)
        request_summary["rejected_tuple_count"] = len(merge_parsed.rejected_rows or [])
        request_summary["canonicalization"] = {
            key: value
            for key, value in merge_canonical_diagnostics.items()
            if key != "canonicalization_map"
        }
        request_summary["supplemented_stakeholders"] = sorted(
            {
                str(row.get("stakeholder", ""))
                for row in merge_parsed.tuples
                if row.get("stakeholder_candidate_match_status") == "unmatched"
            }
        )
        return merge_parsed.tuples, raw_record(
            event_id=event_id,
            model_name=self.model_name,
            request_summary=request_summary,
            raw_response=json.dumps({"stage_extract": stage_raw, "canonical_merge": merge_raw}, ensure_ascii=False),
            parse_success=merge_parsed.parse_success,
            parse_error=merge_parsed.parse_error,
            parse_diagnostics={
                "stage_candidates": stage_parsed.tuples,
                "stage_rejected_rows": stage_parsed.rejected_rows or [],
                "rejected_rows": merge_parsed.rejected_rows or [],
                "stage_canonicalization_map": stage_canonical_diagnostics.get("canonicalization_map", []),
                "canonicalization_map": merge_canonical_diagnostics.get("canonicalization_map", []),
            },
        )

    def _fallback_to_legacy_single_pass(
        self,
        *,
        event: dict[str, Any],
        chain: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        stakeholder_candidates: list[str],
        selection_metadata: dict[str, Any] | None,
        dry_run: bool,
        hide_chain_in_prompt: bool,
        skip_chain_ranking: bool,
        enforce_candidate_constraints: bool,
        prior_api_calls: int,
        fallback_reason: str,
        stage_candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        legacy_tuples, legacy_record = self.attribute_event(
            event=event,
            chain=chain,
            evidence_items=evidence_items,
            stakeholder_candidates=stakeholder_candidates,
            selection_metadata=selection_metadata,
            dry_run=dry_run,
            hide_chain_in_prompt=hide_chain_in_prompt,
            skip_chain_ranking=skip_chain_ranking,
            enforce_candidate_constraints=enforce_candidate_constraints,
            use_stage_attribution=False,
        )
        summary = legacy_record.setdefault("request_summary", {})
        summary["fallback_mode"] = "legacy_single_pass"
        summary["fallback_reason"] = fallback_reason
        summary["stage_candidate_count"] = len(stage_candidates)
        summary["api_calls_made"] = prior_api_calls + int(summary.get("api_calls_made", 0) or 0)
        diagnostics = legacy_record.setdefault("parse_diagnostics", {})
        diagnostics["stage_candidates"] = stage_candidates
        for row in legacy_tuples:
            row["attribution_pass"] = "legacy_single_pass"
        return legacy_tuples, legacy_record

    def _parse_llm_response(
        self,
        response: Any,
        event_id: str,
        allowed_evidence_ids: set[str],
        *,
        stakeholder_candidates: list[str],
        evidence_context_by_id: dict[str, dict[str, Any]],
    ) -> ParseResult:
        return parse_response(
            response,
            event_id=event_id,
            allowed_evidence_ids=allowed_evidence_ids,
            allowed_stakeholders=stakeholder_candidates,
            evidence_context_by_id=evidence_context_by_id,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response_id=getattr(response, "response_id", ""),
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
    oracle_evidence_ids_by_event: dict[str, list[str]] | None = None,
    dry_run: bool = False,
    hide_chain_in_prompt: bool = False,
    skip_chain_ranking: bool = False,
    use_ner_extraction: bool = False,
    selector_mode: str = "chain_aware",
    method_version: str = METHOD_VERSION,
    max_tuples_per_event: int = MAX_TUPLES_PER_EVENT,
    seed: int = 42,
    enforce_candidate_constraints: bool | None = None,
    use_stage_attribution: bool | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_events = select_events(events, event_ids=event_ids, max_events=max_events)
    chains_by_event = {str(chain.get("event_id", "")): chain for chain in chains}
    evidence_by_event = group_by_event(evidence_rows)
    stakeholders_by_event = stakeholder_candidates_by_event(graph_nodes)
    if selector_mode not in SELECTOR_MODES:
        raise ValueError(f"unknown evidence selector mode: {selector_mode}")
    if enforce_candidate_constraints is None:
        enforce_candidate_constraints = False
    if use_stage_attribution is None:
        use_stage_attribution = method_version == SOE_V3_METHOD_VERSION
    attributor = SchemaAttributor(
        llm_client=llm_client,
        model_name=model_name,
        max_tuples_per_event=max_tuples_per_event,
        method_version=method_version,
    )

    tuples: list[dict[str, Any]] = []
    stage_candidates: list[dict[str, Any]] = []
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
        event_evidence_rows = evidence_by_event.get(event_id, [])
        graph_candidates = stakeholders_by_event.get(event_id)
        candidate_scope = "event_graph"
        if graph_candidates is None:
            graph_candidates = stakeholders_by_event.get("__global__", [])
            candidate_scope = "global_fallback"
        initial_stakeholder_candidates = build_event_stakeholder_inventory(event, graph_candidates, event_evidence_rows)
        oracle_evidence_ids = (oracle_evidence_ids_by_event or {}).get(event_id)
        effective_selector_mode = "oracle" if oracle_evidence_ids is not None else selector_mode
        selection = select_evidence_for_prompt(
            event=event,
            chain=chain,
            evidence_rows=event_evidence_rows,
            max_evidence=max_evidence_per_event,
            mode=effective_selector_mode,
            oracle_evidence_ids=oracle_evidence_ids,
            seed=seed,
            stakeholder_candidates=initial_stakeholder_candidates,
        )
        evidence_items = selection.evidence
        stakeholder_candidates = build_event_stakeholder_inventory(
            event,
            initial_stakeholder_candidates,
            evidence_items,
        )
        if use_ner_extraction and llm_client is not None:
            try:
                from episoa.attribution.ner_extractor import build_ner_stakeholder_inventory
                ner_inventory = build_ner_stakeholder_inventory(
                    event=event,
                    graph_candidates=stakeholder_candidates,
                    evidence_items=evidence_items,
                    llm_client=llm_client,
                )
                seen = set(stakeholder_candidates)
                for name in ner_inventory:
                    if name not in seen:
                        stakeholder_candidates.append(name)
                        seen.add(name)
            except Exception:
                pass
        selection_metadata = {
            "method_version": method_version,
            "attribution_mode": ATTRIBUTION_MODE,
            "selector_mode": effective_selector_mode,
            "enforce_candidate_constraints": enforce_candidate_constraints,
            "selection_diagnostics": selection.diagnostics,
            "stakeholder_candidate_scope": candidate_scope,
            "initial_stakeholder_candidates": initial_stakeholder_candidates,
            "canonical_stakeholder_inventory": stakeholder_candidates,
        }
        selection_metadata.update(selection.diagnostics)
        if not evidence_items:
            no_chain_context_events.append(event_id)
            continue
        try:
            event_tuples, record = attributor.attribute_event(
                event=event,
                chain=chain,
                evidence_items=evidence_items,
                stakeholder_candidates=stakeholder_candidates,
                selection_metadata=selection_metadata,
                dry_run=dry_run,
                hide_chain_in_prompt=hide_chain_in_prompt,
                skip_chain_ranking=skip_chain_ranking,
                enforce_candidate_constraints=enforce_candidate_constraints,
                use_stage_attribution=use_stage_attribution,
            )
            raw_records.append(record)
            diagnostics = record.get("parse_diagnostics") if isinstance(record.get("parse_diagnostics"), dict) else {}
            for stage_row in diagnostics.get("stage_candidates", []) or []:
                if isinstance(stage_row, dict):
                    copied = dict(stage_row)
                    copied["selection_diagnostics"] = selection.diagnostics
                    stage_candidates.append(copied)
            api_calls += int(record.get("request_summary", {}).get("api_calls_made", 0) or 0)
            if record.get("parse_success") is False:
                parse_failed_events.append(event_id)
            if not event_tuples:
                empty_tuple_events.append(event_id)
            for row in event_tuples:
                row["selection_diagnostics"] = selection.diagnostics
            tuples.extend(event_tuples)
        except Exception as exc:
            api_failures += 1
            raw_records.append(
                raw_record(
                    event_id=event_id,
                    model_name=model_name,
                    request_summary={
                        "num_evidence": len(evidence_items),
                        "api_calls_made": 0,
                        "method_version": method_version,
                        "attribution_mode": ATTRIBUTION_MODE,
                        "chain_confidence": chain.get("chain_confidence", 0),
                        "prompt_chars": 0,
                        "selected_evidence_ids": [
                            str(item.get("evidence_id", ""))
                            for item in evidence_items
                            if item.get("evidence_id")
                        ],
                        "hide_chain_in_prompt": hide_chain_in_prompt,
                        "skip_chain_ranking": skip_chain_ranking,
                        "selector_mode": effective_selector_mode,
                        "selection_diagnostics": selection.diagnostics,
                    },
                    raw_response="",
                    parse_success=False,
                    parse_error=str(exc),
                )
            )

    candidates_path = output_dir / "candidate_soa_tuples.jsonl"
    stage_candidates_path = output_dir / "stage_soa_candidates.jsonl"
    raw_path = output_dir / "raw_llm_responses.jsonl"
    table_path = output_dir / "schema_attribution_table.csv"
    summary_path = output_dir / "schema_attribution_summary.json"

    write_jsonl(candidates_path, tuples)
    write_jsonl(stage_candidates_path, stage_candidates)
    write_jsonl(raw_path, raw_records)
    write_tuple_table(table_path, tuples)
    write_stakeholder_candidate_scope_table(output_dir / "stakeholder_candidate_scope.csv", raw_records)
    write_canonicalization_map_table(output_dir / "canonicalization_map.csv", raw_records)
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
        method_version=method_version,
        selector_mode=selector_mode,
        max_tuples_per_event=max_tuples_per_event,
    )
    summary["stage_soa_candidates_path"] = str(stage_candidates_path)
    summary["num_stage_soa_candidates"] = len(stage_candidates)
    summary["use_stage_attribution"] = bool(use_stage_attribution)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def assert_no_total_api_failure(summary: dict[str, Any], output_dir: str | Path) -> None:
    """Fail fast when attribution produced only API failures."""
    api_calls = int(summary.get("num_api_calls", 0) or 0)
    api_failures = int(summary.get("num_api_failures", 0) or 0)
    if api_calls > 0 or api_failures == 0:
        return

    output_dir = Path(output_dir)
    raise RuntimeError(
        "Schema attribution made zero successful API calls and recorded "
        f"{api_failures} API failures. Treating the run as failed instead of "
        "writing all-zero metrics. Inspect "
        f"{output_dir / 'schema_attribution_summary.json'} and "
        f"{output_dir / 'raw_llm_responses.jsonl'}."
    )


def parse_response(
    raw_response: Any,
    *,
    event_id: str,
    allowed_evidence_ids: set[str],
    allowed_stakeholders: list[str] | None = None,
    evidence_context_by_id: dict[str, dict[str, Any]] | None = None,
    model_name: str,
    prompt_version: str = PROMPT_VERSION,
    raw_response_id: str = "",
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
    rejected_rows: list[dict[str, Any]] = []
    seen_cluster_ids: set[str] = set()
    for index, row in enumerate(tuples_value):
        if not isinstance(row, dict):
            rejected_rows.append({"row_index": index, "reason": "tuple row must be an object"})
            continue
        sentiment = str(row.get("sentiment", "")).strip()
        if sentiment not in ALLOWED_SENTIMENT:
            rejected_rows.append({"row_index": index, "reason": f"invalid sentiment: {sentiment}"})
            continue
        stage = str(row.get("event_chain_stage") or "unknown").strip()
        if stage not in ALLOWED_STAGE:
            stage = "unknown"
        support = str(row.get("support_status") or "candidate_unclear").strip()
        if support not in ALLOWED_SUPPORT:
            rejected_rows.append({"row_index": index, "reason": f"invalid support_status: {support}"})
            continue
        raw_evidence_ids = dedupe([str(eid).strip() for eid in row.get("evidence_ids", []) if str(eid).strip()])
        unknown_evidence_ids = [eid for eid in raw_evidence_ids if eid not in allowed_evidence_ids]
        if unknown_evidence_ids:
            rejected_rows.append(
                {
                    "row_index": index,
                    "reason": "unknown evidence_id",
                    "unknown_evidence_ids": unknown_evidence_ids,
                }
            )
            continue
        evidence_ids = raw_evidence_ids
        if not evidence_ids:
            rejected_rows.append({"row_index": index, "reason": "missing evidence_ids"})
            continue
        stakeholder = str(row.get("stakeholder", "")).strip()
        opinion = truncate_text(row.get("opinion", ""), MAX_OPINION_CHARS)
        rationale = truncate_text(row.get("rationale", ""), MAX_RATIONALE_CHARS)
        if not stakeholder or not opinion or not rationale:
            rejected_rows.append({"row_index": index, "reason": "missing stakeholder, opinion, or rationale"})
            continue
        if row.get("canonical_tuple") is not True:
            rejected_rows.append({"row_index": index, "reason": "canonical_tuple must be true"})
            continue
        stakeholder_cluster_id = str(row.get("stakeholder_cluster_id") or "").strip()
        if not stakeholder_cluster_id:
            rejected_rows.append({"row_index": index, "reason": "missing stakeholder_cluster_id"})
            continue
        stakeholder_match = best_stakeholder_match(stakeholder, allowed_stakeholders or [])
        match_status = "matched" if stakeholder_match else ("unmatched" if allowed_stakeholders else "no_candidates")
        opinion_split_reason = str(row.get("opinion_split_reason") or "").strip()
        if stakeholder_cluster_id in seen_cluster_ids and not opinion_split_reason:
            rejected_rows.append(
                {
                    "row_index": index,
                    "reason": "duplicate stakeholder_cluster_id without opinion_split_reason",
                    "stakeholder_cluster_id": stakeholder_cluster_id,
                }
            )
            continue
        seen_cluster_ids.add(stakeholder_cluster_id)
        stakeholder_id = make_stakeholder_id(event_id, stakeholder_match or stakeholder)
        opinion_id = make_opinion_id(event_id, opinion)
        stage_id = f"stage:{event_id}:{stage}"
        spans = evidence_spans_for_tuple(evidence_ids, evidence_context_by_id or {})
        stage_candidate_ids = normalize_string_list(row.get("stage_candidate_ids", []), max_items=40, max_chars=100)
        output.append(
            {
                "event_id": event_id,
                "tuple_id": f"{event_id}_SOA_{len(output) + 1:03d}",
                "stakeholder": stakeholder,
                "stakeholder_id": stakeholder_id,
                "opinion": opinion,
                "opinion_id": opinion_id,
                "sentiment": sentiment,
                "rationale": rationale,
                "evidence_ids": evidence_ids,
                "evidence_spans": spans,
                "event_chain_stage": stage,
                "stage_id": stage_id,
                "support_status": support,
                "confidence": clamp_float(row.get("confidence", 0.0)),
                "stakeholder_cluster_id": stakeholder_cluster_id,
                "stakeholder_aliases": normalize_string_list(row.get("stakeholder_aliases", []), max_items=12, max_chars=80),
                "canonical_tuple": True,
                "opinion_split_reason": opinion_split_reason,
                "stakeholder_candidate_match_status": match_status,
                "matched_stakeholder_candidate": stakeholder_match or "",
                "stage_candidate_ids": stage_candidate_ids,
                "model_name": model_name,
                "prompt_version": prompt_version,
                "raw_response_id": raw_response_id,
                "created_at": now_iso(),
            }
        )
    return ParseResult(output, True, None, rejected_rows)


def parse_stage_response(
    raw_response: Any,
    *,
    event_id: str,
    allowed_evidence_ids: set[str],
    evidence_context_by_id: dict[str, dict[str, Any]] | None = None,
    model_name: str,
    prompt_version: str = PROMPT_VERSION,
    raw_response_id: str = "",
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
    candidates_value = payload.get("stage_candidates", [])
    if not isinstance(candidates_value, list):
        return ParseResult([], False, "stage_candidates must be a list")

    output: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    for index, row in enumerate(candidates_value):
        if not isinstance(row, dict):
            rejected_rows.append({"row_index": index, "reason": "stage candidate row must be an object"})
            continue
        sentiment = str(row.get("sentiment", "")).strip()
        if sentiment not in ALLOWED_SENTIMENT:
            rejected_rows.append({"row_index": index, "reason": f"invalid sentiment: {sentiment}"})
            continue
        stage = str(row.get("event_chain_stage") or "unknown").strip()
        if stage not in ALLOWED_STAGE:
            stage = "unknown"
        evidence_ids = dedupe([str(eid).strip() for eid in row.get("evidence_ids", []) if str(eid).strip()])
        unknown_evidence_ids = [eid for eid in evidence_ids if eid not in allowed_evidence_ids]
        if unknown_evidence_ids:
            rejected_rows.append(
                {"row_index": index, "reason": "unknown evidence_id", "unknown_evidence_ids": unknown_evidence_ids}
            )
            continue
        if not evidence_ids:
            rejected_rows.append({"row_index": index, "reason": "missing evidence_ids"})
            continue
        stakeholder = str(row.get("stakeholder", "")).strip()
        opinion = truncate_text(row.get("opinion", ""), MAX_OPINION_CHARS)
        rationale = truncate_text(row.get("rationale", ""), MAX_RATIONALE_CHARS)
        if not stakeholder or not opinion:
            rejected_rows.append({"row_index": index, "reason": "missing stakeholder or opinion"})
            continue
        stage_candidate_id = str(row.get("stage_candidate_id") or f"{event_id}_STAGE_{len(output) + 1:03d}").strip()
        spans = normalize_stage_spans(row.get("evidence_spans", []), evidence_ids, evidence_context_by_id or {})
        output.append(
            {
                "event_id": event_id,
                "stage_candidate_id": stage_candidate_id,
                "stakeholder": stakeholder,
                "opinion": opinion,
                "sentiment": sentiment,
                "event_chain_stage": stage,
                "rationale": rationale,
                "evidence_ids": evidence_ids,
                "evidence_spans": spans,
                "confidence": clamp_float(row.get("confidence", 0.0)),
                "model_name": model_name,
                "prompt_version": prompt_version,
                "raw_response_id": raw_response_id,
                "created_at": now_iso(),
            }
        )
    return ParseResult(output, True, None, rejected_rows)


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
    skip_chain_ranking: bool = False,
) -> list[dict[str, Any]]:
    mode = "quality_topk" if skip_chain_ranking else "chain_aware"
    return select_evidence_for_prompt(
        event=event,
        chain=chain,
        evidence_rows=evidence_rows,
        max_evidence=max_evidence,
        mode=mode,
    ).evidence


def select_oracle_prompt_evidence(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    oracle_evidence_ids: list[str],
    max_evidence: int,
    skip_chain_ranking: bool = False,
) -> list[dict[str, Any]]:
    """Select prompt evidence while forcing gold-support evidence IDs first."""
    mode = "oracle"
    return select_evidence_for_prompt(
        event=event,
        chain=chain,
        evidence_rows=evidence_rows,
        oracle_evidence_ids=oracle_evidence_ids,
        max_evidence=max_evidence,
        mode=mode,
    ).evidence


def _select_evidence_by_non_chain_baseline(
    *,
    event: dict[str, Any],
    chain: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    max_evidence: int,
) -> list[dict[str, Any]]:
    """Select evidence using a non-chain baseline score.

    Ranking uses only quality score, source balance, and stakeholder signal.
    Chain fields are copied later for prompt context when a chain-enabled
    setting asks to hide only the ranking component.
    """
    chain_scores = chain_metadata_by_evidence(chain)

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in evidence_rows:
        quality = float(row.get("quality_score", 0) or 0)
        stakeholder_signal = evidence_stakeholder_signal(row, event)
        composite = 0.7 * quality + 0.3 * stakeholder_signal
        scored.append((composite, row))

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_counts: dict[str, int] = {}
    remaining = sorted(scored, key=lambda x: x[0], reverse=True)

    while len(selected) < max_evidence and remaining:
        best_item: dict[str, Any] | None = None
        best_score = -1.0
        best_idx = -1
        for i, (base_score, row) in enumerate(remaining):
            source = str(row.get("source_type") or row.get("source") or "unknown")
            source_count = source_counts.get(source, 0)
            diversity_bonus = 0.2 if source_count == 0 else 0.0
            adjusted = base_score + diversity_bonus
            if adjusted > best_score:
                best_score = adjusted
                best_item = row
                best_idx = i

        if best_item is None:
            break

        remaining.pop(best_idx)
        eid = str(best_item.get("evidence_id", ""))
        if not eid or eid in seen:
            continue

        cs = chain_scores.get(eid, {})
        stage_name = str(cs.get("stage") or "unknown")
        selected.append(normalize_prompt_evidence(
            {"evidence_id": eid, "stage": stage_name,
             "final_stage_score": cs.get("final_stage_score", ""),
             "event_relevance_score": cs.get("event_relevance_score", "")},
            best_item, stage_name,
        ))
        seen.add(eid)
        source = str(best_item.get("source_type") or best_item.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

    return selected


def chain_metadata_by_evidence(chain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for stage in chain.get("stages", []):
        stage_name = str(stage.get("stage", "unknown"))
        for item in stage.get("evidence", []):
            eid = str(item.get("evidence_id", ""))
            if not eid:
                continue
            current = metadata.get(eid)
            score = float(item.get("final_stage_score", item.get("score", 0)) or 0)
            if current is None or score > float(current.get("final_stage_score", 0) or 0):
                metadata[eid] = {
                    "stage": stage_name,
                    "event_relevance_score": item.get("event_relevance_score", ""),
                    "final_stage_score": item.get("final_stage_score", item.get("score", "")),
                }
    return metadata


def evidence_stakeholder_signal(row: dict[str, Any], event: dict[str, Any]) -> float:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("stakeholder_hint", "stance_hint", "title", "text")
    )
    hints = [str(item).strip() for item in event.get("stakeholder_hints", []) if str(item).strip()]
    hits = 0
    for hint in hints:
        if hint and hint in text:
            hits += 1
    if row.get("stakeholder_hint"):
        hits += 1
    return min(1.0, hits / 3)


def best_stakeholder_match(stakeholder: str, candidates: list[str]) -> str | None:
    if not candidates:
        return None
    scored: list[tuple[float, str]] = []
    for candidate in candidates:
        candidate = str(candidate).strip()
        if not candidate:
            continue
        if stakeholder == candidate or stakeholder in candidate or candidate in stakeholder:
            scored.append((1.0, candidate))
        else:
            scored.append((char_overlap(stakeholder, candidate), candidate))
    if not scored:
        return None
    score, candidate = max(scored, key=lambda item: item[0])
    return candidate if score >= 0.35 else None


def char_overlap(left: str, right: str) -> float:
    left_set = set(str(left or ""))
    right_set = set(str(right or ""))
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def build_event_stakeholder_inventory(
    event: dict[str, Any],
    graph_candidates: list[str] | None,
    evidence_rows: list[dict[str, Any]] | None = None,
    stage_candidates: list[dict[str, Any]] | None = None,
    *,
    max_items: int = MAX_STAKEHOLDER_CANDIDATES,
) -> list[str]:
    """Build an event-scoped candidate inventory without reading gold tuples."""
    raw: list[str] = []
    raw.extend(str(item) for item in graph_candidates or [])
    raw.extend(str(item) for item in event.get("stakeholder_hints", []) or [])
    anchors = event.get("anchor_entities") if isinstance(event.get("anchor_entities"), dict) else {}
    for value in anchors.values():
        if isinstance(value, list):
            raw.extend(str(item) for item in value)
        else:
            raw.append(str(value))
    for row in evidence_rows or []:
        if row.get("stakeholder_hint"):
            raw.append(str(row.get("stakeholder_hint")))
    for row in stage_candidates or []:
        raw.append(str(row.get("stakeholder") or ""))
        raw.extend(str(item) for item in row.get("stakeholder_aliases", []) or [])

    candidates: list[str] = []
    for value in raw:
        candidate = normalize_stakeholder_label(value)
        if not candidate:
            continue
        if is_pseudo_stakeholder(candidate, event):
            continue
        candidates.append(candidate)
    return dedupe(candidates)[:max_items]


def normalize_stakeholder_label(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[，。；：、\s]+|[，。；：、\s]+$", "", text)
    text = re.sub(r"^(记者|媒体|报道称|报道|据悉|其中|同时|目前|对此)", "", text).strip()
    return text[:80]


def is_pseudo_stakeholder(stakeholder: str, event: dict[str, Any] | None = None) -> bool:
    name = normalize_stakeholder_label(stakeholder)
    if not name:
        return True
    compact = normalize_token(name)
    if name in GENERIC_STAKEHOLDER_LABELS or compact in {normalize_token(item) for item in GENERIC_STAKEHOLDER_LABELS}:
        return True
    if event:
        event_name = normalize_token(str(event.get("event_name") or ""))
        if event_name and normalize_token(name) == event_name:
            return True
    if name.endswith("项目") or "改造项目" in name or "建设项目" in name:
        return True
    if any(term in name for term in ISSUE_DESCRIPTOR_TERMS) and not any(term in name for term in SPECIFIC_ACTOR_TERMS):
        return True
    if any(term in name for term in PSEUDO_STAKEHOLDER_TERMS) and not any(term in name for term in ACTOR_HINT_TERMS):
        return True
    if ("媒体" in name or "报道" in name) and not any(term in name for term in ("记者", "报社", "电视台", "新闻社")):
        return True
    return False


def canonicalize_tuple_rows(
    rows: list[dict[str, Any]],
    *,
    event: dict[str, Any],
    stakeholder_candidates: list[str],
    evidence_items: list[dict[str, Any]],
    stage_candidates: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inventory = build_event_stakeholder_inventory(event, stakeholder_candidates, evidence_items, stage_candidates)
    canonical_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    dropped = 0
    remapped = 0
    for row in rows:
        original = str(row.get("stakeholder") or "").strip()
        canonical, action, reason = canonical_stakeholder(original, inventory, event)
        mapping_rows.append(
            {
                "event_id": event.get("event_id", ""),
                "original_stakeholder": original,
                "canonical_stakeholder": canonical,
                "action": action,
                "reason": reason,
                "tuple_id": row.get("tuple_id", ""),
            }
        )
        if action == "drop":
            dropped += 1
            continue
        new_row = dict(row)
        if canonical != original:
            remapped += 1
            aliases = normalize_string_list(new_row.get("stakeholder_aliases", []), max_items=12, max_chars=80)
            new_row["stakeholder_aliases"] = dedupe([original, *aliases, canonical])[:12]
        new_row["stakeholder"] = canonical
        new_row["stakeholder_id"] = make_stakeholder_id(str(event.get("event_id", "")), canonical)
        new_row["matched_stakeholder_candidate"] = canonical if canonical in inventory else str(new_row.get("matched_stakeholder_candidate") or "")
        new_row["stakeholder_candidate_match_status"] = "matched" if canonical in inventory else ("unmatched" if inventory else "no_candidates")
        new_row["canonicalization_action"] = action
        new_row["canonicalization_reason"] = reason
        canonical_rows.append(new_row)

    merged_rows, merge_count = merge_duplicate_canonical_rows(canonical_rows, str(event.get("event_id", "")))
    merged_rows = promote_generic_stakeholders(merged_rows, event)
    diagnostics = {
        "candidate_inventory": inventory,
        "candidate_inventory_count": len(inventory),
        "input_count": len(rows),
        "output_count": len(merged_rows),
        "dropped_pseudo_stakeholder_count": dropped,
        "remapped_stakeholder_count": remapped,
        "merged_duplicate_count": merge_count,
        "canonicalization_map": mapping_rows,
    }
    return merged_rows, diagnostics


def canonicalize_stage_candidate_rows(
    rows: list[dict[str, Any]],
    *,
    event: dict[str, Any],
    stakeholder_candidates: list[str],
    evidence_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inventory = build_event_stakeholder_inventory(event, stakeholder_candidates, evidence_items, rows)
    output: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    dropped = 0
    remapped = 0
    for row in rows:
        original = str(row.get("stakeholder") or "").strip()
        canonical, action, reason = canonical_stakeholder(original, inventory, event)
        mapping_rows.append(
            {
                "event_id": event.get("event_id", ""),
                "original_stakeholder": original,
                "canonical_stakeholder": canonical,
                "action": action,
                "reason": reason,
                "stage_candidate_id": row.get("stage_candidate_id", ""),
            }
        )
        if action == "drop":
            dropped += 1
            continue
        copied = dict(row)
        copied["stakeholder"] = canonical
        copied["canonicalization_action"] = action
        copied["canonicalization_reason"] = reason
        if canonical != original:
            remapped += 1
        output.append(copied)
    return output, {
        "candidate_inventory": inventory,
        "candidate_inventory_count": len(inventory),
        "input_count": len(rows),
        "output_count": len(output),
        "dropped_pseudo_stakeholder_count": dropped,
        "remapped_stakeholder_count": remapped,
        "canonicalization_map": mapping_rows,
    }


def canonical_stakeholder(
    stakeholder: str,
    inventory: list[str],
    event: dict[str, Any],
) -> tuple[str, str, str]:
    original = normalize_stakeholder_label(stakeholder)
    match = best_stakeholder_match(original, inventory)
    if is_pseudo_stakeholder(original, event):
        if match and not is_pseudo_stakeholder(match, event):
            return match, "remap", "pseudo_stakeholder_mapped_to_inventory"
        return original, "drop", "pseudo_stakeholder"
    if match and not is_pseudo_stakeholder(match, event):
        if match != original:
            return match, "remap", "inventory_alias_match"
        return original, "keep", "inventory_exact"
    return original, "keep", "evidence_supported_outside_inventory"


def merge_duplicate_canonical_rows(rows: list[dict[str, Any]], event_id: str) -> tuple[list[dict[str, Any]], int]:
    merged: list[dict[str, Any]] = []
    merge_count = 0
    for row in rows:
        target = None
        for existing in merged:
            if existing.get("stakeholder") != row.get("stakeholder"):
                continue
            if tuple_opinion_similarity(str(existing.get("opinion", "")), str(row.get("opinion", ""))) >= 0.90:
                target = existing
                break
        if target is None:
            merged.append(dict(row))
            continue
        merge_count += 1
        target["evidence_ids"] = dedupe([*target.get("evidence_ids", []), *row.get("evidence_ids", [])])
        target["stage_candidate_ids"] = dedupe([*target.get("stage_candidate_ids", []), *row.get("stage_candidate_ids", [])])
        target["stakeholder_aliases"] = dedupe([*target.get("stakeholder_aliases", []), *row.get("stakeholder_aliases", [])])[:12]
        if len(str(row.get("opinion", ""))) > len(str(target.get("opinion", ""))):
            target["opinion"] = row.get("opinion", "")
            target["opinion_id"] = make_opinion_id(event_id, str(target.get("opinion", "")))
        if len(str(row.get("rationale", ""))) > len(str(target.get("rationale", ""))):
            target["rationale"] = row.get("rationale", "")
        target["confidence"] = max(float(target.get("confidence", 0) or 0), float(row.get("confidence", 0) or 0))
        target["sentiment"] = merge_sentiment(str(target.get("sentiment", "")), str(row.get("sentiment", "")))

    stakeholder_clusters: dict[str, str] = {}
    for index, row in enumerate(merged, start=1):
        row["tuple_id"] = f"{event_id}_SOA_{index:03d}"
        stakeholder = str(row.get("stakeholder", ""))
        seen_before = stakeholder in stakeholder_clusters
        cluster_id = stakeholder_clusters.setdefault(stakeholder, f"stakeholder_{len(stakeholder_clusters) + 1:03d}")
        if seen_before and row.get("stakeholder_cluster_id") != cluster_id:
            row["opinion_split_reason"] = row.get("opinion_split_reason") or "same stakeholder has distinct evidence-supported opinion/action"
        row["stakeholder_cluster_id"] = cluster_id
    return merged, merge_count


def tuple_opinion_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right or left in right or right in left:
        return 1.0
    return char_overlap(left, right)


def merge_sentiment(left: str, right: str) -> str:
    if not left:
        return right
    if not right or left == right:
        return left
    if "mixed" in {left, right}:
        return "mixed"
    if {left, right} <= {"positive", "negative"}:
        return "mixed"
    if "neutral" in {left, right}:
        other = left if right == "neutral" else right
        return other
    return left


def _specificity_score(name: str) -> int:
    """Score stakeholder name specificity. Higher = more specific."""
    if not name:
        return 0
    score = len(name)
    specific_indicators = (
        "小区", "社区", "村", "镇", "街道", "区", "市", "省", "局", "委",
        "公司", "集团", "医院", "学校", "法院", "检察院", "派出所",
        "业主", "居民", "家长", "学生", "患者", "律师", "记者",
        "女士", "先生", "男子", "女子", "人",
        "店", "厂", "中心", "部", "厅", "处",
    )
    for indicator in specific_indicators:
        if indicator in name:
            score += 10
    if name in GENERIC_STAKEHOLDER_LABELS:
        score = 0
    return score


def promote_generic_stakeholders(
    rows: list[dict[str, Any]],
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    """Post-process: drop tuples whose stakeholder is a generic label with no specific aliases.

    When the LLM merge step collapses specific entities into generic labels like
    "居民/公众" with no meaningful specific aliases, the generic tuple adds noise
    without providing useful information. Drop these noise tuples rather than promote them.
    """
    result = []
    for row in rows:
        stakeholder = str(row.get("stakeholder", "")).strip()
        if stakeholder in GENERIC_STAKEHOLDER_LABELS:
            aliases = row.get("stakeholder_aliases", []) or []
            aliases = [str(a).strip() for a in aliases if str(a).strip()]
            non_generic = [a for a in aliases if a not in GENERIC_STAKEHOLDER_LABELS]
            if not non_generic:
                continue
        result.append(row)
    return result


def make_stakeholder_id(event_id: str, stakeholder: str) -> str:
    return f"stakeholder_entity:{event_id}:{normalize_token(stakeholder)}"


def make_opinion_id(event_id: str, opinion: str) -> str:
    return f"opinion:{event_id}:{normalize_token(opinion)[:32]}"


def evidence_spans_for_tuple(evidence_ids: list[str], evidence_context_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        item = evidence_context_by_id.get(evidence_id, {})
        span_rows = item.get("evidence_spans") if isinstance(item.get("evidence_spans"), list) else []
        if span_rows:
            for span in span_rows:
                if not isinstance(span, dict):
                    continue
                spans.append(
                    {
                        "evidence_id": str(span.get("evidence_id") or evidence_id),
                        "char_start": int(span.get("char_start", 0) or 0),
                        "char_end": int(span.get("char_end", 0) or 0),
                        "text": truncate_text(span.get("text", ""), 500),
                    }
                )
            continue
        text = str(item.get("text_excerpt") or item.get("text") or "")
        spans.append(
            {
                "evidence_id": evidence_id,
                "char_start": 0,
                "char_end": min(len(text), 500),
                "text": text[:500],
            }
        )
    return spans


def normalize_stage_spans(
    value: Any,
    evidence_ids: list[str],
    evidence_context_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id") or "").strip()
            if evidence_id not in evidence_ids:
                continue
            spans.append(
                {
                    "evidence_id": evidence_id,
                    "char_start": int(item.get("char_start", 0) or 0),
                    "char_end": int(item.get("char_end", 0) or 0),
                    "text": truncate_text(item.get("text", ""), 500),
                }
            )
    return spans or evidence_spans_for_tuple(evidence_ids, evidence_context_by_id)


def infer_stage_candidate_ids(row: dict[str, Any], stage_candidates: list[dict[str, Any]]) -> list[str]:
    evidence_ids = set(str(item) for item in row.get("evidence_ids", []) or [])
    stakeholder = str(row.get("stakeholder", ""))
    matches: list[str] = []
    for candidate in stage_candidates:
        candidate_id = str(candidate.get("stage_candidate_id", ""))
        if not candidate_id:
            continue
        candidate_evidence = set(str(item) for item in candidate.get("evidence_ids", []) or [])
        same_stakeholder = char_overlap(stakeholder, str(candidate.get("stakeholder", ""))) >= 0.35
        if evidence_ids & candidate_evidence or same_stakeholder:
            matches.append(candidate_id)
    return dedupe(matches)


def evidence_spans_from_stage_candidates(
    stage_candidate_ids: list[str],
    stage_candidates: list[dict[str, Any]],
    evidence_ids: list[str],
) -> list[dict[str, Any]]:
    wanted = {str(item).strip() for item in stage_candidate_ids or [] if str(item).strip()}
    allowed_evidence = {str(item).strip() for item in evidence_ids or [] if str(item).strip()}
    if not wanted:
        return []
    spans: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str]] = set()
    for candidate in stage_candidates:
        if str(candidate.get("stage_candidate_id") or "") not in wanted:
            continue
        for span in candidate.get("evidence_spans", []) or []:
            if not isinstance(span, dict):
                continue
            evidence_id = str(span.get("evidence_id") or "").strip()
            if not evidence_id or (allowed_evidence and evidence_id not in allowed_evidence):
                continue
            text = str(span.get("text") or "")
            char_start = int(span.get("char_start") or 0)
            char_end = int(span.get("char_end") or 0)
            key = (evidence_id, char_start, char_end, text)
            if key in seen:
                continue
            seen.add(key)
            spans.append(
                {
                    "evidence_id": evidence_id,
                    "char_start": char_start,
                    "char_end": char_end,
                    "text": text,
                }
            )
    return spans


def normalize_token(value: str) -> str:
    token = re.sub(r"\W+", "_", str(value or "").strip().lower(), flags=re.UNICODE).strip("_")
    return token or "unknown"


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


def format_stage_evidence_blocks(
    evidence_items: list[dict[str, Any]],
    *,
    max_excerpt_chars: int = 360,
    hide_stage: bool = False,
    hide_chain_fields: bool = False,
) -> str:
    lines: list[str] = []
    for item in evidence_items:
        parts = [
            f"- evidence_id: {item.get('evidence_id')}",
        ]
        if not hide_stage and not hide_chain_fields:
            parts.append(f"  stage: {item.get('stage')}")
        parts.extend([
            f"  source: {item.get('source')}",
            f"  domain: {item.get('domain')}",
            f"  url: {item.get('url')}",
            f"  title: {truncate_text(item.get('title', ''), 80)}",
        ])
        if not hide_chain_fields:
            parts.extend([
                f"  final_stage_score: {item.get('final_stage_score')}",
                f"  event_relevance_score: {item.get('event_relevance_score')}",
                f"  selection_score: {item.get('selection_score', '')}",
            ])
        parts.append(f"  text_excerpt: {truncate_text(item.get('text_excerpt', ''), max_excerpt_chars)}")
        lines.append("\n".join(parts))
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
        event_ids = attrs.get("event_ids")
        if isinstance(event_ids, list):
            for event_id in event_ids:
                if str(event_id):
                    by_event.setdefault(str(event_id), set()).add(name)
        event_id = attrs.get("event_id")
        if event_id:
            by_event.setdefault(str(event_id), set()).add(name)
    return {event_id: sorted(values) for event_id, values in by_event.items()} | {"__global__": sorted(global_candidates)}


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
    method_version: str = METHOD_VERSION,
    selector_mode: str = "chain_aware",
    max_tuples_per_event: int = MAX_TUPLES_PER_EVENT,
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
        "method_version": method_version,
        "attribution_mode": ATTRIBUTION_MODE,
        "selector_mode": selector_mode,
        "tuple_limit_policy": "none",
        "max_tuples_per_event_deprecated_noop": max_tuples_per_event,
    }


def write_tuple_table(path: str | Path, tuples: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_id",
        "tuple_id",
        "stakeholder",
        "stakeholder_id",
        "stakeholder_cluster_id",
        "stakeholder_aliases",
        "stakeholder_candidate_match_status",
        "matched_stakeholder_candidate",
        "opinion",
        "opinion_id",
        "canonical_tuple",
        "opinion_split_reason",
        "sentiment",
        "rationale",
        "evidence_ids",
        "evidence_spans",
        "stage_candidate_ids",
        "attribution_pass",
        "event_chain_stage",
        "stage_id",
        "support_status",
        "confidence",
        "selection_diagnostics",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in tuples:
            flat = dict(row)
            flat["evidence_ids"] = "|".join(row.get("evidence_ids", []))
            flat["evidence_spans"] = json.dumps(row.get("evidence_spans", []), ensure_ascii=False)
            flat["stage_candidate_ids"] = "|".join(row.get("stage_candidate_ids", []))
            flat["stakeholder_aliases"] = "|".join(row.get("stakeholder_aliases", []))
            flat["selection_diagnostics"] = json.dumps(row.get("selection_diagnostics", {}), ensure_ascii=False)
            writer.writerow(flat)


def write_stakeholder_candidate_scope_table(path: str | Path, raw_records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event_id",
        "candidate_scope",
        "initial_candidate_count",
        "final_candidate_count",
        "selection_candidate_count",
        "selected_evidence_count",
        "stakeholder_candidate_coverage",
        "initial_stakeholder_candidates",
        "canonical_stakeholder_inventory",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in raw_records:
            summary = record.get("request_summary", {}) if isinstance(record.get("request_summary"), dict) else {}
            selection = summary.get("selection_diagnostics", {}) if isinstance(summary.get("selection_diagnostics"), dict) else {}
            initial = summary.get("initial_stakeholder_candidates", []) or []
            final = summary.get("canonical_stakeholder_inventory") or summary.get("stakeholder_candidates") or []
            writer.writerow(
                {
                    "event_id": record.get("event_id", ""),
                    "candidate_scope": summary.get("stakeholder_candidate_scope", ""),
                    "initial_candidate_count": len(initial),
                    "final_candidate_count": len(final),
                    "selection_candidate_count": selection.get("stakeholder_candidate_count", ""),
                    "selected_evidence_count": selection.get("selected_evidence_count", ""),
                    "stakeholder_candidate_coverage": selection.get("stakeholder_candidate_coverage", ""),
                    "initial_stakeholder_candidates": "|".join(str(item) for item in initial),
                    "canonical_stakeholder_inventory": "|".join(str(item) for item in final),
                }
            )


def write_canonicalization_map_table(path: str | Path, raw_records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event_id",
        "row_source",
        "row_id",
        "original_stakeholder",
        "canonical_stakeholder",
        "action",
        "reason",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in raw_records:
            diagnostics = record.get("parse_diagnostics", {}) if isinstance(record.get("parse_diagnostics"), dict) else {}
            for source_key, row_source in (
                ("stage_canonicalization_map", "stage_candidate"),
                ("canonicalization_map", "tuple"),
            ):
                for row in diagnostics.get(source_key, []) or []:
                    writer.writerow(
                        {
                            "event_id": row.get("event_id") or record.get("event_id", ""),
                            "row_source": row_source,
                            "row_id": row.get("stage_candidate_id") or row.get("tuple_id") or "",
                            "original_stakeholder": row.get("original_stakeholder", ""),
                            "canonical_stakeholder": row.get("canonical_stakeholder", ""),
                            "action": row.get("action", ""),
                            "reason": row.get("reason", ""),
                        }
                    )


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
    parse_diagnostics: dict[str, Any] | None = None,
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
    if parse_diagnostics:
        record["parse_diagnostics"] = parse_diagnostics
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


def normalize_string_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    return dedupe([truncate_text(item, max_chars) for item in raw_values if str(item).strip()])[:max_items]


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
