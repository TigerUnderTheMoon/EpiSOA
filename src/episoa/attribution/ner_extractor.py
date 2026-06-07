"""Named Entity Recognition for stakeholder extraction.

Extracts specific stakeholder entities from evidence text before attribution,
replacing the generic STAKEHOLDER_RULES bucket approach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from episoa.data.loader import read_jsonl
from episoa.llm.client import json_schema_response_format

NER_RESPONSE_FORMAT = json_schema_response_format(
    "ner_stakeholder_response",
    {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "canonical_name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "entity_type": {
                            "type": "string",
                            "enum": [
                                "government_agency",
                                "government_official",
                                "company",
                                "resident_group",
                                "individual",
                                "media",
                                "professional",
                                "judicial_body",
                                "other",
                            ],
                        },
                        "evidence_support": {"type": "string"},
                    },
                    "required": ["canonical_name", "aliases", "entity_type"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["event_id", "entities"],
        "additionalProperties": False,
    },
)

NER_SYSTEM_PROMPT = """You are a named entity recognition system for public event stakeholder extraction.
Your task is to identify ALL distinct stakeholder entities mentioned in the evidence for a given event.

CRITICAL RULES:
1. Each entity must have a SPECIFIC canonical name - never output generic labels like "居民/公众", "相关部门", "公众", "网友", or "社会舆论".
2. Use the most specific name available in the evidence:
   - "美心翡翠明庭小区业主" NOT "居民/公众"
   - "广州市白云区政府" NOT "政府部门"
   - "三元里村党委及村集体" NOT "三元里村"
   - "当事学生" NOT "学生"
   - "受伤居民" NOT "居民"
3. Group all aliases of the same entity together. For example:
   - "成都七中实验学校" and "校方" are the SAME entity
   - "广州市市场监管局" and "市监局" are the SAME entity
4. For resident/public groups, extract the most specific description:
   - "受影响居民/市民" NOT "居民/公众"
   - "明尚西苑居民/业主" NOT "居民"
   - "被征收人" NOT "居民"
5. Include ALL entities mentioned in the evidence, even minor ones.
6. Return strict JSON only.
"""

NER_USER_PROMPT_TEMPLATE = """event_id: {event_id}
event_name: {event_name}
event_description: {event_description}
stakeholder_hints: {stakeholder_hints}

evidence:
{evidence_text}

Extract ALL distinct stakeholder entities from the evidence above.
Return strict JSON only."""


@dataclass
class NEREntity:
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "other"
    evidence_support: str = ""


def extract_stakeholder_entities_llm(
    *,
    event: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    llm_client: Any,
) -> list[NEREntity]:
    """Extract specific stakeholder entities using LLM."""
    evidence_text = _format_evidence_for_ner(evidence_items, max_items=30, max_chars=6000)
    user_prompt = NER_USER_PROMPT_TEMPLATE.format(
        event_id=event.get("event_id", ""),
        event_name=event.get("event_name", ""),
        event_description=event.get("event_description", "")[:500],
        stakeholder_hints=json.dumps(event.get("stakeholder_hints", []), ensure_ascii=False),
        evidence_text=evidence_text,
    )
    response = llm_client.chat(
        system_prompt=NER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_format=NER_RESPONSE_FORMAT,
    )
    return _parse_ner_response(response, event.get("event_id", ""))


def _format_evidence_for_ner(
    evidence_items: list[dict[str, Any]],
    max_items: int = 30,
    max_chars: int = 6000,
) -> str:
    """Format evidence items for NER prompt."""
    blocks = []
    total_chars = 0
    for item in evidence_items[:max_items]:
        eid = str(item.get("evidence_id", ""))
        text = str(item.get("text_excerpt", "") or item.get("text", ""))[:300]
        block = f"[{eid}] {text}"
        if total_chars + len(block) > max_chars:
            break
        blocks.append(block)
        total_chars += len(block)
    return "\n".join(blocks)


def _parse_ner_response(response: Any, event_id: str) -> list[NEREntity]:
    """Parse NER LLM response into structured entities."""
    from episoa.attribution.schema_attributor import normalize_raw_response
    raw_text = normalize_raw_response(response)
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return []
    if data.get("event_id") != event_id and event_id:
        pass
    entities = data.get("entities", [])
    result = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("canonical_name", "")).strip()
        if not name or _is_generic_stakeholder(name):
            continue
        aliases = [str(a) for a in ent.get("aliases", []) if str(a).strip()]
        if name not in aliases:
            aliases.insert(0, name)
        result.append(NEREntity(
            canonical_name=name,
            aliases=aliases,
            entity_type=str(ent.get("entity_type", "other")),
            evidence_support=str(ent.get("evidence_support", "")),
        ))
    return result


def _is_generic_stakeholder(name: str) -> bool:
    """Check if a stakeholder name is too generic."""
    generic_labels = {
        "居民/公众", "公众", "网友", "社会舆论", "相关部门", "政府部门",
        "有关部门", "项目方", "事件", "报道", "媒体", "社会",
    }
    return name in generic_labels


def build_ner_stakeholder_inventory(
    event: dict[str, Any],
    graph_candidates: list[str],
    evidence_items: list[dict[str, Any]],
    llm_client: Any | None = None,
) -> list[str]:
    """Build stakeholder inventory from NER + graph + hints.

    Uses LLM-based NER when available, falls back to graph candidates.
    """
    all_names: list[str] = []

    # 1. Graph candidates (rule-based, but with deduplicated labels)
    for name in graph_candidates:
        if not _is_generic_stakeholder(name):
            all_names.append(name)

    # 2. Event hints
    for hint in event.get("stakeholder_hints", []):
        hint_str = str(hint).strip()
        if hint_str and not _is_generic_stakeholder(hint_str):
            all_names.append(hint_str)

    # 3. Anchor entities
    anchor_entities = event.get("anchor_entities", {})
    if isinstance(anchor_entities, dict):
        for key, val in anchor_entities.items():
            if isinstance(val, str) and val.strip() and not _is_generic_stakeholder(val):
                all_names.append(val.strip())
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str) and v.strip() and not _is_generic_stakeholder(v):
                        all_names.append(v.strip())

    # 4. LLM-based NER (if client provided)
    if llm_client is not None:
        try:
            ner_entities = extract_stakeholder_entities_llm(
                event=event,
                evidence_items=evidence_items,
                llm_client=llm_client,
            )
            for ent in ner_entities:
                if ent.canonical_name not in all_names:
                    all_names.append(ent.canonical_name)
                for alias in ent.aliases:
                    if alias not in all_names and alias != ent.canonical_name:
                        all_names.append(alias)
        except Exception:
            pass

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for name in all_names:
        normalized = name.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    return unique[:50]