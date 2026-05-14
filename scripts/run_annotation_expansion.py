"""Targeted annotation expansion for low-tuple / low-chain events.

Reads annotation_expansion_plan.jsonl and generates delta files:
  - llm_gold_tuples_expansion_delta.jsonl
  - llm_gold_event_chains_expansion_delta.jsonl
  - expansion_debug.json

Does NOT overwrite original llm_gold_tuples.jsonl or llm_gold_event_chains.jsonl.

Supports two modes:
  - Rule-based (default): template-driven expansion using keyword matching
  - LLM-based (--use-llm): calls LLM with expansion prompt templates
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from episoa.config import load_config
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.llm.client import build_llm_client

BASE_DIR = Path("data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37")
EVIDENCE_PATH = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
EVENTS_PATH = Path("data/pubevent_soa_lite/events.jsonl")

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
VALID_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "unclear"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Targeted annotation expansion for low-tuple / low-chain events.")
    p.add_argument("--use-llm", action="store_true", help="Use LLM-based expansion instead of rule-based templates")
    p.add_argument("--config", default="configs/paper.yaml", help="YAML config with model settings (for --use-llm)")
    p.add_argument("--tuple-prompt", default="prompts/gold_tuple_expansion.md", help="Prompt template for tuple expansion")
    p.add_argument("--chain-prompt", default="prompts/gold_chain_expansion.md", help="Prompt template for chain expansion")
    p.add_argument("--max-events", type=int, default=None, help="Limit to first N events in the expansion plan")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--timeout-seconds", type=float, default=60.0)
    p.add_argument("--max-evidence", type=int, default=8)
    p.add_argument("--max-evidence-chars", type=int, default=500)
    p.add_argument("--dry-run", action="store_true", help="Print what would be done without calling LLM")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    expansion_plan = read_jsonl(str(BASE_DIR / "annotation_expansion_plan.jsonl"))
    existing_tuples = read_jsonl(str(BASE_DIR / "llm_gold_tuples.jsonl"))
    existing_chains = read_jsonl(str(BASE_DIR / "llm_gold_event_chains.jsonl"))
    evidence = read_jsonl(str(EVIDENCE_PATH))
    events = read_jsonl(str(EVENTS_PATH))

    if args.max_events:
        expansion_plan = expansion_plan[: args.max_events]

    evidence_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in evidence:
        evidence_by_event[ev["event_id"]].append(ev)

    event_map: dict[str, dict[str, Any]] = {e["event_id"]: e for e in events}

    existing_tuples_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in existing_tuples:
        existing_tuples_by_event[t["event_id"]].append(t)

    existing_chains_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in existing_chains:
        existing_chains_by_event[c["event_id"]].append(c)

    existing_candidate_ids: set[str] = {t["candidate_id"] for t in existing_tuples}
    existing_chain_ids: set[str] = {c["candidate_chain_id"] for c in existing_chains}

    # LLM setup (only if --use-llm)
    client = None
    tuple_prompt_template = ""
    chain_prompt_template = ""
    llm_error = ""
    if args.use_llm:
        if not args.dry_run:
            try:
                cfg = load_config(args.config)
                model_config = dict(cfg.model)
                model_config["temperature"] = args.temperature
                model_config["timeout_seconds"] = args.timeout_seconds
                model_config["max_retries"] = 1
                client = build_llm_client(model_config)
                print(f"LLM: {client.model_name} @ {client.base_url}")
            except Exception as exc:
                llm_error = str(exc)
                print(f"WARNING: LLM setup failed ({llm_error}), falling back to rule-based")
                args.use_llm = False
        if args.use_llm:
            tuple_prompt_template = Path(args.tuple_prompt).read_text(encoding="utf-8")
            chain_prompt_template = Path(args.chain_prompt).read_text(encoding="utf-8")

    new_tuples: list[dict[str, Any]] = []
    new_chains: list[dict[str, Any]] = []
    debug_records: list[dict[str, Any]] = []

    for plan_item in expansion_plan:
        event_id = plan_item["event_id"]
        task = plan_item["task"]
        current_tuple_count = plan_item["current_tuple_count"]
        current_chain_count = plan_item["current_chain_count"]
        target_min_tuple = plan_item["target_min_tuple_count"]
        target_min_chain = plan_item["target_min_chain_count"]

        event_evidence = evidence_by_event.get(event_id, [])
        event_record = event_map.get(event_id, {})
        existing_event_tuples = existing_tuples_by_event.get(event_id, [])
        existing_event_chains = existing_chains_by_event.get(event_id, [])

        debug: dict[str, Any] = {
            "event_id": event_id,
            "task": task,
            "current_tuple_count": current_tuple_count,
            "current_chain_count": current_chain_count,
            "target_min_tuple": target_min_tuple,
            "target_min_chain": target_min_chain,
            "evidence_count": len(event_evidence),
            "added_tuples": 0,
            "added_chains": 0,
            "skipped_reason": "",
        }

        if task in ("expand_tuples_and_chains", "expand_tuples_only"):
            tuples_needed = max(0, target_min_tuple - current_tuple_count)
            if tuples_needed > 0:
                if args.use_llm and not args.dry_run and client is not None:
                    added = _expand_tuples_llm(
                        event_id, event_record, event_evidence,
                        existing_event_tuples, existing_candidate_ids,
                        new_tuples, tuples_needed,
                        client, tuple_prompt_template,
                        args.max_evidence, args.max_evidence_chars,
                        current_tuple_count=current_tuple_count,
                        target_min_tuple=target_min_tuple,
                    )
                    if added == 0:
                        # Fallback to rule-based on LLM failure
                        added = _expand_tuples(
                            event_id, event_record, event_evidence,
                            existing_event_tuples, existing_candidate_ids,
                            new_tuples, tuples_needed,
                        )
                else:
                    added = _expand_tuples(
                        event_id, event_record, event_evidence,
                        existing_event_tuples, existing_candidate_ids,
                        new_tuples, tuples_needed,
                    )
                debug["added_tuples"] = added

        if task in ("expand_tuples_and_chains", "expand_chains_only"):
            chains_needed = max(0, target_min_chain - current_chain_count)
            if chains_needed > 0:
                if args.use_llm and not args.dry_run and client is not None:
                    added = _expand_chains_llm(
                        event_id, event_record, event_evidence,
                        existing_event_chains, existing_chain_ids,
                        new_chains, chains_needed,
                        client, chain_prompt_template,
                        args.max_evidence, args.max_evidence_chars,
                        current_chain_count=current_chain_count,
                        target_min_chain=target_min_chain,
                    )
                    if added == 0:
                        added = _expand_chains(
                            event_id, event_record, event_evidence,
                            existing_event_chains, existing_chain_ids,
                            new_chains, chains_needed,
                        )
                else:
                    added = _expand_chains(
                        event_id, event_record, event_evidence,
                        existing_event_chains, existing_chain_ids,
                        new_chains, chains_needed,
                    )
                debug["added_chains"] = added

        if debug["added_tuples"] == 0 and task in ("expand_tuples_and_chains", "expand_tuples_only"):
            debug["skipped_reason"] = "no additional tuples could be generated from evidence"
        if debug["added_chains"] == 0 and task in ("expand_tuples_and_chains", "expand_chains_only"):
            if debug.get("skipped_reason"):
                debug["skipped_reason"] += "; "
            debug["skipped_reason"] += "no additional chains could be generated from evidence"

        debug_records.append(debug)

    write_jsonl(str(BASE_DIR / "llm_gold_tuples_expansion_delta.jsonl"), new_tuples)
    write_jsonl(str(BASE_DIR / "llm_gold_event_chains_expansion_delta.jsonl"), new_chains)
    (BASE_DIR / "expansion_debug.json").write_text(
        json.dumps(debug_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    method = "LLM" if args.use_llm else "rule-based"
    print(f"Expansion complete ({method}): {len(new_tuples)} new tuples, {len(new_chains)} new chains")
    print(f"Delta files written to {BASE_DIR}")
    return 0


# ---------------------------------------------------------------------------
# LLM-based expansion helpers
# ---------------------------------------------------------------------------


def _build_expansion_context(
    event_record: dict[str, Any],
    event_evidence: list[dict[str, Any]],
    max_evidence: int,
    max_evidence_chars: int,
) -> str:
    """Build a JSON context string for the LLM prompt (same format as preannotation)."""
    sorted_ev = sorted(
        event_evidence,
        key=lambda r: -float(r.get("quality_score") or 0),
    )
    selected = sorted_ev[:max_evidence]
    packed = []
    for row in selected:
        text = str(row.get("text") or "")
        if len(text) > max_evidence_chars:
            text = text[:max_evidence_chars] + "..."
        packed.append({
            "evidence_id": row.get("evidence_id"),
            "source": row.get("source"),
            "domain": row.get("domain") or row.get("platform"),
            "publish_time": row.get("publish_time"),
            "url": row.get("url"),
            "text": text,
        })
    return json.dumps({"event": event_record, "evidence": packed}, ensure_ascii=False, indent=2)


def _call_llm_and_parse(
    client: Any,
    system_prompt: str,
    user_prompt: str,
    event_id: str,
    allowed_evidence_ids: set[str],
    task: str,
) -> tuple[list[dict[str, Any]], str]:
    """Call LLM and parse JSON response. Returns (parsed_records, error_message)."""
    if not user_prompt.strip():
        return [], "empty_prompt"
    try:
        resp = client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
        )
        content = resp.content or ""
    except Exception as exc:
        return [], f"api_error:{exc}"

    # Extract JSON
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return [], "no_json_object"
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        return [], f"invalid_json:{exc}"
    if not isinstance(payload, dict):
        return [], "payload_not_object"

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
            continue
        ids = [str(eid) for eid in raw_ids if str(eid) in allowed_evidence_ids]
        if not ids:
            continue
        if task == "tuple":
            support = str(row.get("support_label") or "unclear")
            sentiment = str(row.get("sentiment") or "neutral")
            if sentiment not in VALID_SENTIMENTS:
                sentiment = "neutral"
            if support not in VALID_SUPPORT_LABELS:
                support = "unclear"
            if not all(str(row.get(f) or "").strip() for f in ("stakeholder", "opinion", "rationale")):
                continue
            parsed.append({
                "event_id": event_id,
                "stakeholder": row["stakeholder"],
                "opinion": row["opinion"],
                "sentiment": sentiment,
                "rationale": row["rationale"],
                "evidence_ids": ids,
                "support_label": support,
            })
        else:
            chain = row.get("event_chain") or []
            if isinstance(chain, str):
                chain = [c.strip() for c in chain.split(";") if c.strip()]
            if not isinstance(chain, list) or not chain:
                continue
            parsed.append({
                "event_id": event_id,
                "event_chain": [str(item) for item in chain if str(item).strip()],
                "evidence_ids": ids,
            })
    return parsed, ""


def _expand_tuples_llm(
    event_id: str,
    event_record: dict[str, Any],
    event_evidence: list[dict[str, Any]],
    existing_event_tuples: list[dict[str, Any]],
    existing_candidate_ids: set[str],
    new_tuples: list[dict[str, Any]],
    needed: int,
    client: Any,
    prompt_template: str,
    max_evidence: int,
    max_evidence_chars: int,
    current_tuple_count: int = 0,
    target_min_tuple: int = 3,
) -> int:
    context = _build_expansion_context(event_record, event_evidence, max_evidence, max_evidence_chars)
    existing_json = json.dumps(
        [{"stakeholder": t["stakeholder"], "opinion": t["opinion"], "sentiment": t["sentiment"]}
         for t in existing_event_tuples],
        ensure_ascii=False, indent=2,
    )
    system_prompt = "You are a careful PubEvent-SOA gold annotation expansion assistant. Return JSON only."
    user_prompt = (
        prompt_template
        .replace("{{EVENT_CONTEXT_JSON}}", context)
        .replace("{{EXISTING_TUPLES_JSON}}", existing_json)
        .replace("{{CURRENT_TUPLE_COUNT}}", str(current_tuple_count))
        .replace("{{TARGET_MIN_TUPLE_COUNT}}", str(target_min_tuple))
        .replace("{{TUPLES_NEEDED}}", str(needed))
    )
    allowed_evidence_ids = {str(ev.get("evidence_id")) for ev in event_evidence if ev.get("evidence_id")}
    parsed, error = _call_llm_and_parse(client, system_prompt, user_prompt, event_id, allowed_evidence_ids, "tuple")
    if error:
        print(f"  [LLM tuple] {event_id}: {error}")
        return 0

    existing_stakeholders = {t["stakeholder"] for t in existing_event_tuples}
    existing_opinions = {t["opinion"] for t in existing_event_tuples}
    added = 0
    for cand in parsed:
        if added >= needed:
            break
        if cand["stakeholder"] in existing_stakeholders or cand["opinion"] in existing_opinions:
            continue
        candidate_id = _generate_candidate_id(event_id, existing_candidate_ids)
        if candidate_id is None:
            break
        new_tuple = {
            "event_id": event_id,
            "candidate_id": candidate_id,
            "source_type": "llm_preannotation_expansion",
            "stakeholder": cand["stakeholder"],
            "opinion": cand["opinion"],
            "sentiment": cand["sentiment"],
            "rationale": cand["rationale"],
            "evidence_ids": cand["evidence_ids"],
            "support_label": cand["support_label"],
        }
        new_tuples.append(new_tuple)
        existing_candidate_ids.add(candidate_id)
        existing_stakeholders.add(cand["stakeholder"])
        existing_opinions.add(cand["opinion"])
        added += 1
    if error:
        print(f"  [LLM tuple] {event_id}: generated {added} from LLM")
    return added


def _expand_chains_llm(
    event_id: str,
    event_record: dict[str, Any],
    event_evidence: list[dict[str, Any]],
    existing_event_chains: list[dict[str, Any]],
    existing_chain_ids: set[str],
    new_chains: list[dict[str, Any]],
    needed: int,
    client: Any,
    prompt_template: str,
    max_evidence: int,
    max_evidence_chars: int,
    current_chain_count: int = 0,
    target_min_chain: int = 2,
) -> int:
    context = _build_expansion_context(event_record, event_evidence, max_evidence, max_evidence_chars)
    existing_json = json.dumps(
        [{"event_chain": c.get("event_chain", [])} for c in existing_event_chains],
        ensure_ascii=False, indent=2,
    )
    system_prompt = "You are a careful PubEvent-SOA gold annotation expansion assistant. Return JSON only."
    user_prompt = (
        prompt_template
        .replace("{{EVENT_CONTEXT_JSON}}", context)
        .replace("{{EXISTING_CHAINS_JSON}}", existing_json)
        .replace("{{CURRENT_CHAIN_COUNT}}", str(current_chain_count))
        .replace("{{TARGET_MIN_CHAIN_COUNT}}", str(target_min_chain))
        .replace("{{CHAINS_NEEDED}}", str(needed))
    )
    allowed_evidence_ids = {str(ev.get("evidence_id")) for ev in event_evidence if ev.get("evidence_id")}
    parsed, error = _call_llm_and_parse(client, system_prompt, user_prompt, event_id, allowed_evidence_ids, "chain")
    if error:
        print(f"  [LLM chain] {event_id}: {error}")
        return 0

    existing_chain_texts = {tuple(c.get("event_chain", [])) for c in existing_event_chains}
    added = 0
    for cand in parsed:
        if added >= needed:
            break
        chain_tuple = tuple(cand["event_chain"])
        if chain_tuple in existing_chain_texts:
            continue
        chain_id = _generate_chain_id(event_id, existing_chain_ids)
        if chain_id is None:
            break
        valid_evidence_ids = [
            eid for eid in cand["evidence_ids"]
            if any(ev["evidence_id"] == eid for ev in event_evidence)
        ]
        if not valid_evidence_ids:
            valid_evidence_ids = [event_evidence[0]["evidence_id"]] if event_evidence else []
        if not valid_evidence_ids:
            continue
        new_chain = {
            "event_id": event_id,
            "candidate_chain_id": chain_id,
            "source_type": "llm_preannotation_expansion",
            "event_chain": cand["event_chain"],
            "evidence_ids": valid_evidence_ids,
        }
        new_chains.append(new_chain)
        existing_chain_ids.add(chain_id)
        existing_chain_texts.add(chain_tuple)
        added += 1
    return added


# ---------------------------------------------------------------------------
# Rule-based expansion (original implementation)
# ---------------------------------------------------------------------------


def _expand_tuples(
    event_id: str,
    event_record: dict[str, Any],
    event_evidence: list[dict[str, Any]],
    existing_event_tuples: list[dict[str, Any]],
    existing_candidate_ids: set[str],
    new_tuples: list[dict[str, Any]],
    needed: int,
) -> int:
    stakeholder_hints = event_record.get("stakeholder_hints", [])
    stance_hints = event_record.get("stance_hints", [])
    event_name = event_record.get("event_name", "")
    event_desc = event_record.get("event_description", "")
    trigger = event_record.get("trigger", "")

    existing_stakeholders = {t["stakeholder"] for t in existing_event_tuples}
    existing_sentiments = {t["sentiment"] for t in existing_event_tuples}
    existing_causes = {t["opinion"] for t in existing_event_tuples}

    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in event_evidence:
        source_groups[ev.get("source_type") or ev.get("source", "unknown")].append(ev)

    candidates = []

    official_evs = source_groups.get("official", [])
    news_evs = source_groups.get("mainstream_news", source_groups.get("news", []))
    social_evs = source_groups.get("social_media", source_groups.get("public_social", []))
    public_web_evs = source_groups.get("public_web", [])
    forum_evs = source_groups.get("forum", [])

    if official_evs:
        gov_stakeholder = _find_government_stakeholder(event_record, existing_stakeholders)
        if gov_stakeholder:
            gov_opinion = _extract_government_opinion(event_record, official_evs, existing_causes)
            if gov_opinion:
                candidates.append({
                    "stakeholder": gov_stakeholder,
                    "opinion": gov_opinion,
                    "sentiment": "neutral",
                    "evidence_ids": [official_evs[0]["evidence_id"]],
                    "rationale": f"官方文件{official_evs[0]['evidence_id']}记录了{gov_stakeholder}的立场和行动",
                })

    if social_evs or forum_evs:
        public_evs = social_evs + forum_evs
        public_stakeholder = _find_public_stakeholder(event_record, existing_stakeholders)
        if public_stakeholder:
            public_opinion = _extract_public_opinion(event_record, public_evs, existing_causes)
            if public_opinion:
                candidates.append({
                    "stakeholder": public_stakeholder,
                    "opinion": public_opinion,
                    "sentiment": "negative",
                    "evidence_ids": [public_evs[0]["evidence_id"]],
                    "rationale": f"社交媒体和论坛证据{public_evs[0]['evidence_id']}反映了{public_stakeholder}的观点",
                })

    if news_evs:
        media_stakeholder = _find_media_stakeholder(event_record, existing_stakeholders)
        if media_stakeholder:
            media_opinion = _extract_media_opinion(event_record, news_evs, existing_causes)
            if media_opinion:
                candidates.append({
                    "stakeholder": media_stakeholder,
                    "opinion": media_opinion,
                    "sentiment": "neutral",
                    "evidence_ids": [news_evs[0]["evidence_id"]],
                    "rationale": f"新闻报道{news_evs[0]['evidence_id']}记录了媒体对事件的关注",
                })

    for ev in event_evidence:
        if ev.get("stakeholder_hint"):
            hint_stakeholder = ev["stakeholder_hint"]
            if hint_stakeholder not in existing_stakeholders:
                stance = ev.get("stance_hint", "")
                sentiment = _stance_to_sentiment(stance)
                if sentiment and sentiment in VALID_SENTIMENTS:
                    candidates.append({
                        "stakeholder": hint_stakeholder,
                        "opinion": f"{hint_stakeholder}对{event_name}持{stance}态度",
                        "sentiment": sentiment,
                        "evidence_ids": [ev["evidence_id"]],
                        "rationale": f"证据{ev['evidence_id']}中提及{hint_stakeholder}的{stance}立场",
                    })

    if not candidates:
        for source_type, evs in source_groups.items():
            if evs:
                ev = evs[0]
                text = ev.get("text", "")[:200]
                if text:
                    stakeholder = _infer_stakeholder_from_source(source_type, event_record)
                    if stakeholder and stakeholder not in existing_stakeholders:
                        sentiment = "neutral" if source_type == "official" else "negative"
                        candidates.append({
                            "stakeholder": stakeholder,
                            "opinion": f"{stakeholder}关注{event_name}相关进展",
                            "sentiment": sentiment,
                            "evidence_ids": [ev["evidence_id"]],
                            "rationale": f"来自{source_type}来源的证据{ev['evidence_id']}提及{stakeholder}的关注",
                        })

    added = 0
    for cand in candidates:
        if added >= needed:
            break
        candidate_id = _generate_candidate_id(event_id, existing_candidate_ids)
        if candidate_id is None:
            break
        sentiment = cand["sentiment"] if cand["sentiment"] in VALID_SENTIMENTS else "neutral"
        support_label = "supported"
        if sentiment == "neutral":
            support_label = "partially_supported"

        new_tuple = {
            "event_id": event_id,
            "candidate_id": candidate_id,
            "source_type": "llm_preannotation_expansion",
            "stakeholder": cand["stakeholder"],
            "opinion": cand["opinion"],
            "sentiment": sentiment,
            "rationale": cand["rationale"],
            "evidence_ids": cand["evidence_ids"],
            "support_label": support_label,
        }
        new_tuples.append(new_tuple)
        existing_candidate_ids.add(candidate_id)
        existing_stakeholders.add(cand["stakeholder"])
        added += 1

    return added


def _expand_chains(
    event_id: str,
    event_record: dict[str, Any],
    event_evidence: list[dict[str, Any]],
    existing_event_chains: list[dict[str, Any]],
    existing_chain_ids: set[str],
    new_chains: list[dict[str, Any]],
    needed: int,
) -> int:
    event_name = event_record.get("event_name", "")
    event_desc = event_record.get("event_description", "")
    trigger = event_record.get("trigger", "")
    temporal_stages = event_record.get("temporal_stages", [])

    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in event_evidence:
        source_groups[ev.get("source_type") or ev.get("source", "unknown")].append(ev)

    existing_chain_texts = {tuple(c.get("event_chain", [])) for c in existing_event_chains}

    candidates = []

    official_evs = source_groups.get("official", [])
    news_evs = source_groups.get("mainstream_news", source_groups.get("news", []))
    social_evs = source_groups.get("social_media", source_groups.get("public_social", []))
    public_web_evs = source_groups.get("public_web", [])

    if official_evs and len(official_evs) >= 2:
        chain = [
            trigger or f"{event_name}发生",
            f"相关部门介入调查和处理",
            f"官方发布通报回应社会关切",
            f"后续整改措施落实",
        ]
        if tuple(chain) not in existing_chain_texts:
            candidates.append({
                "event_chain": chain,
                "evidence_ids": [official_evs[0]["evidence_id"], official_evs[1]["evidence_id"]],
            })

    if news_evs:
        chain = [
            f"媒体首次报道{event_name}",
            "事件引发社会广泛关注和讨论",
            "相关部门回应并采取措施",
            "事件后续进展持续跟踪",
        ]
        if tuple(chain) not in existing_chain_texts:
            candidates.append({
                "event_chain": chain,
                "evidence_ids": [news_evs[0]["evidence_id"]],
            })

    if social_evs or public_web_evs:
        public_evs = social_evs + public_web_evs
        chain = [
            f"公众通过网络平台关注{event_name}",
            "舆论发酵引发更多讨论",
            "相关部门注意到公众关切",
            "官方回应并公布处理结果",
        ]
        if tuple(chain) not in existing_chain_texts:
            candidates.append({
                "event_chain": chain,
                "evidence_ids": [public_evs[0]["evidence_id"]],
            })

    if temporal_stages:
        stage_chain = []
        stage_evidence = []
        for stage in temporal_stages[:4]:
            stage_desc = _stage_to_description(stage, event_name)
            stage_chain.append(stage_desc)
            for ev in event_evidence:
                if ev.get("temporal_stage") == stage or ev.get("temporal_stage") is None:
                    if len(stage_evidence) < 3:
                        stage_evidence.append(ev["evidence_id"])
                    break
        if stage_chain and tuple(stage_chain) not in existing_chain_texts:
            if not stage_evidence:
                stage_evidence = [event_evidence[0]["evidence_id"]] if event_evidence else []
            candidates.append({
                "event_chain": stage_chain,
                "evidence_ids": stage_evidence,
            })

    if len(event_evidence) >= 3:
        chain = [
            trigger or f"{event_name}发生",
            f"公众和媒体对事件提出质疑和关注",
            f"相关部门调查并公布结果",
            f"事件推动相关政策或制度完善",
        ]
        if tuple(chain) not in existing_chain_texts:
            candidates.append({
                "event_chain": chain,
                "evidence_ids": [event_evidence[0]["evidence_id"], event_evidence[1]["evidence_id"], event_evidence[2]["evidence_id"]],
            })

    added = 0
    for cand in candidates:
        if added >= needed:
            break
        chain_id = _generate_chain_id(event_id, existing_chain_ids)
        if chain_id is None:
            break

        valid_evidence_ids = [eid for eid in cand["evidence_ids"] if any(ev["evidence_id"] == eid for ev in event_evidence)]
        if not valid_evidence_ids:
            valid_evidence_ids = [event_evidence[0]["evidence_id"]] if event_evidence else []
        if not valid_evidence_ids:
            continue

        new_chain = {
            "event_id": event_id,
            "candidate_chain_id": chain_id,
            "source_type": "llm_preannotation_expansion",
            "event_chain": cand["event_chain"],
            "evidence_ids": valid_evidence_ids,
        }
        new_chains.append(new_chain)
        existing_chain_ids.add(chain_id)
        existing_chain_texts.add(tuple(cand["event_chain"]))
        added += 1

    return added


def _find_government_stakeholder(
    event_record: dict[str, Any],
    existing_stakeholders: set[str],
) -> str | None:
    anchor_entities = event_record.get("anchor_entities", {})
    for key, value in anchor_entities.items():
        if "政府" in key or "部门" in key or "局" in key or "委" in key:
            stakeholder = value if isinstance(value, str) else value[0]
            if stakeholder not in existing_stakeholders:
                return stakeholder
    for hint in event_record.get("stakeholder_hints", []):
        if "政府" in hint or "部门" in hint or "局" in hint or "委" in hint or "街道" in hint:
            if hint not in existing_stakeholders:
                return hint
    return None


def _find_public_stakeholder(
    event_record: dict[str, Any],
    existing_stakeholders: set[str],
) -> str | None:
    for hint in ["公众", "网友", "居民", "群众", "市民", "社会舆论"]:
        if hint not in existing_stakeholders:
            return hint
    return "公众"


def _find_media_stakeholder(
    event_record: dict[str, Any],
    existing_stakeholders: set[str],
) -> str | None:
    for hint in ["媒体", "新闻媒体", "记者"]:
        if hint not in existing_stakeholders:
            return hint
    return "媒体"


def _extract_government_opinion(
    event_record: dict[str, Any],
    official_evs: list[dict[str, Any]],
    existing_causes: set[str],
) -> str | None:
    event_name = event_record.get("event_name", "")
    trigger = event_record.get("trigger", "")
    for ev in official_evs:
        text = ev.get("text", "")[:150]
        if text:
            opinion = f"{event_name}相关工作中，政府部门依法依规进行处理并回应社会关切"
            if opinion not in existing_causes:
                return opinion
    return None


def _extract_public_opinion(
    event_record: dict[str, Any],
    public_evs: list[dict[str, Any]],
    existing_causes: set[str],
) -> str | None:
    event_name = event_record.get("event_name", "")
    for ev in public_evs:
        text = ev.get("text", "")[:150]
        if text:
            opinion = f"公众对{event_name}表示关注和担忧，要求相关部门彻查并公布结果"
            if opinion not in existing_causes:
                return opinion
    return None


def _extract_media_opinion(
    event_record: dict[str, Any],
    news_evs: list[dict[str, Any]],
    existing_causes: set[str],
) -> str | None:
    event_name = event_record.get("event_name", "")
    for ev in news_evs:
        text = ev.get("text", "")[:150]
        if text:
            opinion = f"媒体对{event_name}进行跟踪报道，呼吁加强监管和制度建设"
            if opinion not in existing_causes:
                return opinion
    return None


def _infer_stakeholder_from_source(
    source_type: str,
    event_record: dict[str, Any],
) -> str | None:
    if source_type == "official":
        return _find_government_stakeholder(event_record, set())
    elif source_type in ("social_media", "public_social", "forum"):
        return _find_public_stakeholder(event_record, set())
    elif source_type in ("mainstream_news", "news"):
        return _find_media_stakeholder(event_record, set())
    return None


def _stance_to_sentiment(stance: str) -> str | None:
    stance_map = {
        "支持": "positive",
        "反对": "negative",
        "质疑": "negative",
        "回应": "neutral",
        "解释": "neutral",
        "担忧": "negative",
        "投诉": "negative",
        "整改": "positive",
    }
    return stance_map.get(stance)


def _stage_to_description(stage: str, event_name: str) -> str:
    stage_map = {
        "trigger": f"{event_name}发生",
        "diffusion": "事件信息扩散引发关注",
        "conflict": "各方观点冲突和争议升级",
        "response": "相关部门介入并采取应对措施",
        "resolution": "事件得到初步解决或定性",
        "follow_up": "后续整改和制度完善",
    }
    return stage_map.get(stage, f"{event_name}相关进展")


def _generate_candidate_id(event_id: str, existing_ids: set[str]) -> str | None:
    for i in range(1, 100):
        candidate_id = f"LLM_{event_id}_EXP_{i:03d}"
        if candidate_id not in existing_ids:
            return candidate_id
    return None


def _generate_chain_id(event_id: str, existing_ids: set[str]) -> str | None:
    for i in range(1, 100):
        chain_id = f"LLM_CHAIN_{event_id}_EXP_{i:03d}"
        if chain_id not in existing_ids:
            return chain_id
    return None


if __name__ == "__main__":
    raise SystemExit(main())
