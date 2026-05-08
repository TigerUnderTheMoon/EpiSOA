"""Rule-based Event-chain Retrieval for candidate EpiSOA evidence.

This module deliberately does not read gold labels, call LLMs, or call search
APIs. It only ranks already collected evidence into candidate event-chain
stages for later human audit and downstream attribution.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
import re
from typing import Any

from episoa.data.schema import EventRecord, EvidenceRecord


STAGES = ["trigger", "diffusion", "conflict", "response", "resolution", "follow_up"]
CORE_STAGES = {"trigger", "conflict", "response"}
DEDUP_STAGE_PRIORITY = ["trigger", "conflict", "response", "resolution", "diffusion", "follow_up"]

GENERIC_TOPIC_TERMS = {
    "旧城改造",
    "城市更新",
    "拆迁",
    "补偿",
    "安置",
    "征收",
    "棚户区",
    "老旧小区",
    "旧改",
    "补偿标准",
}
EVENT_STOP_TERMS = GENERIC_TOPIC_TERMS | {
    "争议",
    "居民",
    "利益",
    "公共事件",
    "标准",
    "方案",
    "项目",
    "问题",
    "事件",
    "形成",
    "情况",
    "相关",
    "某市",
    "某地",
    "不满",
    "质疑",
    "回应",
    "解释",
    "支持",
    "反对",
    "担忧",
    "建议",
    "观望",
    "投诉",
    "举报",
    "维权",
    "答复",
    "说明",
    "通报",
    "推进",
    "落实",
    "处理",
    "结果",
    "政策",
    "规定",
    "办法",
    "通知",
    "文件",
    "政府",
    "官方",
    "部门",
    "媒体",
    "专家",
    "市民",
    "网友",
    "群众",
    "住建部门",
    "住建局",
}
GENERIC_PATTERNS = [
    "什么是",
    "一文看懂",
    "政策解读",
    "新政落地",
    "拆迁新政",
    "2025年老旧小区",
    "2026拆迁新政",
    "补偿标准有哪些",
    "房屋征收补偿标准",
    "暂行办法",
    "补偿标准的通知",
    "棚户区改造办法",
    "法律咨询",
    "律师解答",
    "征收补偿条例",
    "旧改是什么意思",
]

STAGE_KEYWORDS = {
    "trigger": [
        "事件发生",
        "冲突发生",
        "项目启动",
        "启动改造",
        "发布征收公告",
        "启动",
        "发布",
        "公告",
        "通知",
        "规划",
        "立项",
    ],
    "diffusion": ["网传", "热议", "舆论", "媒体报道", "引发关注", "网友讨论", "传播"],
    "conflict": ["投诉", "质疑", "不满", "反对", "举报", "维权", "纠纷", "矛盾", "争议", "阻挠", "冲突"],
    "response": ["回应", "通报", "答复", "说明", "澄清", "官方回应", "部门表示", "回应称"],
    "resolution": ["整改", "解决", "处理结果", "达成一致", "完成整改", "问题解决", "后续处理", "落实整改"],
    "follow_up": ["后续进展", "复查", "回访", "跟进", "再次回应", "持续处理"],
}
WEAK_TRIGGER_TERMS = {"拆迁", "征收", "公告", "通知", "规划"}
WEAK_DIFFUSION_TERMS = {"关注"}
WEAK_RESOLUTION_TERMS = {"补偿", "安置", "推进", "落实"}
WEAK_FOLLOW_UP_TERMS = {"最新", "进展"}
RESOLUTION_OFFICIAL_TERMS = ["答复", "处理", "回应", "结果"]
STAKEHOLDER_TERMS = [
    "居民",
    "村民",
    "业主",
    "群众",
    "网友",
    "市民",
    "政府",
    "街道办",
    "住建局",
    "开发商",
    "企业",
    "媒体",
    "记者",
    "专家",
    "律师",
]
SOURCE_PRIOR = {
    "official": {"response": 0.9, "resolution": 0.8},
    "public_interaction": {"conflict": 0.8, "diffusion": 0.5},
    "public_social": {"diffusion": 0.8, "conflict": 0.7},
    "forum": {"diffusion": 0.7, "conflict": 0.8},
    "news": {"trigger": 0.6, "diffusion": 0.6, "response": 0.4},
}


class EventChainRetriever:
    def __init__(
        self,
        top_k_per_stage: int = 3,
        max_chain_length: int = 6,
        min_stage_score: float = 0.25,
        min_event_relevance: float = 0.30,
        deduplicate_evidence_across_stages: bool = True,
    ):
        self.top_k_per_stage = top_k_per_stage
        self.max_chain_length = max_chain_length
        self.min_stage_score = min_stage_score
        self.min_event_relevance = min_event_relevance
        self.deduplicate_evidence_across_stages = deduplicate_evidence_across_stages

    def retrieve_for_event(self, event: dict, evidence_rows: list[dict]) -> dict:
        event_id = str(event.get("event_id", ""))
        related = [row for row in evidence_rows if str(row.get("event_id", "")) == event_id]

        stage_candidates: dict[str, list[dict]] = {stage: [] for stage in STAGES}
        relevance_scores: list[float] = []
        generic_penalty_count = 0
        passed_relevance = 0
        duplicate_assignments_removed = 0

        for evidence in related:
            relevance = compute_event_relevance_score(event, evidence)
            relevance_scores.append(float(relevance["score"]))
            if relevance["is_generic_penalized"]:
                generic_penalty_count += 1
            if relevance["score"] < self.min_event_relevance:
                continue
            passed_relevance += 1

            evidence_candidates: list[dict] = []
            for stage in STAGES:
                details = score_evidence_for_stage_details(
                    evidence.get("text", ""),
                    evidence.get("source", ""),
                    stage,
                )
                if details["stage_keyword_score"] <= 0:
                    continue
                final_score = compute_final_stage_score(evidence, details, relevance)
                if final_score < self.min_stage_score:
                    continue
                evidence_candidates.append(evidence_stage_record(evidence, stage, final_score, details, relevance))

            if self.deduplicate_evidence_across_stages and len(evidence_candidates) > 1:
                best = max(evidence_candidates, key=lambda record: (record["final_stage_score"], -stage_priority(record["stage"])))
                stage_candidates[best["stage"]].append(best)
                duplicate_assignments_removed += len(evidence_candidates) - 1
            else:
                for candidate in evidence_candidates:
                    stage_candidates[candidate["stage"]].append(candidate)

        stages = []
        stage_best_scores: dict[str, float] = {}
        for idx, stage in enumerate(STAGES, start=1):
            candidates = sorted(
                stage_candidates[stage],
                key=lambda item: (item["final_stage_score"], parse_time_sort_key(item.get("publish_time"))),
                reverse=True,
            )[: self.top_k_per_stage]
            stage_best_scores[stage] = round(candidates[0]["final_stage_score"], 4) if candidates else 0.0
            stages.append({"stage": stage, "stage_order": idx, "evidence": candidates})

        selected_evidence = [item for stage in stages for item in stage["evidence"]]
        diagnostics = {
            "num_evidence_considered": len(related),
            "num_evidence_passed_relevance": passed_relevance,
            "num_evidence_passing_relevance": passed_relevance,
            "num_evidence_filtered_by_relevance": len(related) - passed_relevance,
            "avg_event_relevance": round(sum(relevance_scores) / len(relevance_scores), 4) if relevance_scores else 0.0,
            "generic_penalty_count": generic_penalty_count,
            "deduplicated_evidence_count": duplicate_assignments_removed,
            "removed_duplicate_stage_assignments": duplicate_assignments_removed,
            "num_stages_covered": sum(1 for stage in stages if stage["evidence"]),
            "source_distribution": dict(Counter(row.get("source", "unknown") for row in related)),
            "stage_best_scores": stage_best_scores,
            "mode": "evidence_only",
            "min_event_relevance": self.min_event_relevance,
            "deduplicate_evidence_across_stages": self.deduplicate_evidence_across_stages,
        }
        missing_stages = [stage["stage"] for stage in stages if not stage["evidence"]]
        return {
            "event_id": event_id,
            "chain_id": f"{event_id}_CHAIN_CANDIDATE",
            "chain_confidence": chain_confidence(stages),
            "stages": stages,
            "missing_stages": missing_stages,
            "retrieval_diagnostics": diagnostics,
        }

    def retrieve_all(self, events: list[dict], evidence_rows: list[dict]) -> list[dict]:
        return [self.retrieve_for_event(event, evidence_rows) for event in events]


def compute_event_relevance_score(event: dict, evidence: dict) -> dict:
    title = str(evidence.get("title", "") or "")
    text = str(evidence.get("text", "") or "")
    combined = f"{title}\n{text}"
    event_id_match = str(evidence.get("event_id", "")) == str(event.get("event_id", ""))

    event_name_terms = extract_event_terms(str(event.get("event_name", "") or ""))
    description_terms = extract_event_terms(str(event.get("event_description", "") or ""))
    seed_terms = normalize_term_list(event.get("seed_keywords", []))
    stakeholder_terms = normalize_term_list(event.get("stakeholder_hints", []))

    matched_event_name_terms = matched_terms(event_name_terms, combined)
    matched_description_terms = matched_terms(description_terms, combined)
    matched_seed_keywords = matched_terms(seed_terms, combined)
    matched_stakeholder_terms = matched_terms(stakeholder_terms, combined)
    matched_event_terms = unique(matched_event_name_terms + matched_description_terms + matched_seed_keywords)

    score = 0.20 if event_id_match else 0.0
    score += weighted_match_score(matched_event_name_terms, title, text, base_weight=0.16, cap=0.34)
    score += weighted_match_score(matched_description_terms, title, text, base_weight=0.10, cap=0.22)
    score += weighted_match_score(matched_seed_keywords, title, text, base_weight=0.12, cap=0.28)
    score += min(0.08, 0.025 * len(matched_stakeholder_terms))

    generic = detect_generic_policy_content(title, text)
    specific_terms = [term for term in matched_event_terms if is_event_specific_term(term)]
    generic_only = bool(generic["is_generic"]) and not specific_terms
    if generic["is_generic"]:
        penalty = generic["penalty"] * (0.15 if specific_terms else 1.0)
        score -= penalty
    if generic_only:
        score = min(score, 0.20)

    score = clamp(score)
    return {
        "score": score,
        "matched_event_terms": matched_event_terms,
        "matched_seed_keywords": matched_seed_keywords,
        "matched_event_name_terms": matched_event_name_terms,
        "matched_description_terms": matched_description_terms,
        "matched_stakeholder_terms": matched_stakeholder_terms,
        "is_generic_penalized": bool(generic["is_generic"]),
        "generic_penalty_terms": generic["matched_terms"],
        "reason": relevance_reason(score, event_id_match, specific_terms, generic_only, generic),
    }


def detect_generic_policy_content(title: str, text: str) -> dict:
    combined = f"{title}\n{text}"
    matched = [term for term in GENERIC_PATTERNS if term and term in combined]
    topic_hits = [term for term in GENERIC_TOPIC_TERMS if term and term in combined]
    all_terms = unique(matched + topic_hits[:4])
    if not all_terms:
        return {"is_generic": False, "matched_terms": [], "penalty": 0.0}
    pattern_weight = 0.08 * len(matched)
    topic_weight = 0.025 * len(topic_hits)
    penalty = min(0.32, 0.10 + pattern_weight + topic_weight)
    return {"is_generic": True, "matched_terms": all_terms, "penalty": round(penalty, 4)}


def score_evidence_for_stage(text: str, source: str, stage: str) -> float:
    details = score_evidence_for_stage_details(text, source, stage)
    return round(clamp(details["stage_keyword_score"] + 0.05 * details["source_prior_component"]), 4)


def score_evidence_for_stage_details(text: str, source: str, stage: str) -> dict:
    if stage not in STAGE_KEYWORDS:
        return {"stage_keyword_score": 0.0, "matched_stage_keywords": [], "source_prior_component": 0.0}
    matched = [term for term in STAGE_KEYWORDS[stage] if term in text]
    weak_matched: list[str] = []
    if stage == "trigger":
        weak_matched = [term for term in WEAK_TRIGGER_TERMS if term in text]
    elif stage == "diffusion":
        weak_matched = [term for term in WEAK_DIFFUSION_TERMS if term in text]
    elif stage == "resolution":
        weak_matched = [term for term in WEAK_RESOLUTION_TERMS if term in text]
        if source == "official" and any(term in text for term in RESOLUTION_OFFICIAL_TERMS):
            matched.append("official_response_result")
    elif stage == "follow_up":
        weak_matched = [term for term in WEAK_FOLLOW_UP_TERMS if term in text]

    strong_hits = len(unique(matched))
    weak_hits = len(unique(weak_matched))
    score = min(1.0, 0.32 * strong_hits + 0.06 * weak_hits)
    if strong_hits == 0:
        if stage in {"resolution", "follow_up", "diffusion"}:
            score = min(score, 0.16)
        elif stage == "trigger":
            score = min(score, 0.20)
    return {
        "stage_keyword_score": round(clamp(score), 4),
        "matched_stage_keywords": unique(matched + weak_matched),
        "source_prior_component": SOURCE_PRIOR.get(source, {}).get(stage, 0.0),
    }


def compute_final_stage_score(evidence: dict, details: dict, relevance: dict) -> float:
    quality = safe_float(evidence.get("quality_score"), 0.5)
    source_prior = safe_float(details.get("source_prior_component"), 0.0)
    text = str(evidence.get("text", "") or "")
    stakeholder_signal = min(1.0, 0.25 * len([term for term in STAKEHOLDER_TERMS if term in text]))
    generic_penalty = 0.12 if relevance.get("is_generic_penalized") else 0.0
    score = (
        0.40 * safe_float(details.get("stage_keyword_score"), 0.0)
        + 0.25 * safe_float(relevance.get("score"), 0.0)
        + 0.15 * quality
        + 0.10 * source_prior
        + 0.10 * stakeholder_signal
        - generic_penalty
    )
    if safe_float(relevance.get("score"), 0.0) < 0.30:
        score = min(score, 0.24)
    return round(clamp(score), 4)


def evidence_stage_record(evidence: dict, stage: str, final_score: float, details: dict, relevance: dict) -> dict:
    quality = safe_float(evidence.get("quality_score"), 0.5)
    source_prior = safe_float(details.get("source_prior_component"), 0.0)
    text = str(evidence.get("text", "") or "")
    stakeholder_signal = min(1.0, 0.25 * len([term for term in STAKEHOLDER_TERMS if term in text]))
    return {
        "evidence_id": evidence.get("evidence_id"),
        "stage": stage,
        "score": final_score,
        "stage_score": final_score,
        "final_stage_score": final_score,
        "source": evidence.get("source", ""),
        "domain": evidence.get("domain", ""),
        "url": evidence.get("url", ""),
        "title": evidence.get("title", ""),
        "text_excerpt": text_excerpt(evidence.get("text", "")),
        "publish_time": evidence.get("publish_time", ""),
        "event_relevance_score": relevance["score"],
        "matched_event_terms": relevance["matched_event_terms"],
        "matched_seed_keywords": relevance["matched_seed_keywords"],
        "matched_event_name_terms": relevance["matched_event_name_terms"],
        "matched_description_terms": relevance["matched_description_terms"],
        "matched_stakeholder_terms": relevance["matched_stakeholder_terms"],
        "matched_stage_keywords": details["matched_stage_keywords"],
        "generic_penalty_terms": relevance["generic_penalty_terms"],
        "is_generic_penalized": relevance["is_generic_penalized"],
        "stage_keyword_score": details["stage_keyword_score"],
        "quality_score_component": round(quality, 4),
        "source_prior_component": round(source_prior, 4),
        "stakeholder_signal_component": round(stakeholder_signal, 4),
    }


def chain_confidence(stages: list[dict]) -> float:
    selected = [item for stage in stages for item in stage.get("evidence", [])]
    if not selected:
        return 0.0
    covered_stages = {stage["stage"] for stage in stages if stage.get("evidence")}
    core_coverage = len(covered_stages & CORE_STAGES) / len(CORE_STAGES)
    stage_coverage = len(covered_stages) / len(STAGES)
    avg_stage_score = sum(safe_float(item.get("final_stage_score"), 0.0) for item in selected) / len(selected)
    avg_event_relevance = sum(safe_float(item.get("event_relevance_score"), 0.0) for item in selected) / len(selected)
    source_diversity = min(1.0, len({item.get("source", "") for item in selected if item.get("source")}) / 4)
    generic_ratio = sum(1 for item in selected if item.get("is_generic_penalized")) / len(selected)
    domain_counts = Counter(item.get("domain", "") for item in selected if item.get("domain"))
    top_domain_ratio = max(domain_counts.values()) / len(selected) if domain_counts else 0.0
    missing_core = 1.0 - core_coverage
    penalty = 0.20 * generic_ratio + 0.15 * max(0.0, top_domain_ratio - 0.5) + 0.20 * missing_core
    if avg_event_relevance < 0.35:
        penalty += 0.15
    confidence = (
        0.28 * core_coverage
        + 0.14 * stage_coverage
        + 0.22 * avg_stage_score
        + 0.24 * avg_event_relevance
        + 0.12 * source_diversity
        - penalty
    )
    confidence = clamp(confidence)
    if avg_event_relevance < 0.30:
        confidence = min(confidence, 0.60)
    return round(confidence, 4)


def build_retrieval_summary(candidates: list[dict], output_path: str) -> dict:
    confidences = [safe_float(item.get("chain_confidence"), 0.0) for item in candidates]
    stage_coverages = Counter(str(item.get("retrieval_diagnostics", {}).get("num_stages_covered", 0)) for item in candidates)
    avg_evidence_per_stage_values = [
        len(stage.get("evidence", []))
        for candidate in candidates
        for stage in candidate.get("stages", [])
    ]
    diagnostics = [candidate.get("retrieval_diagnostics", {}) for candidate in candidates]
    return {
        "num_events": len(candidates),
        "avg_chain_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "stage_coverage_distribution": dict(stage_coverages),
        "events_missing_trigger": [item["event_id"] for item in candidates if "trigger" in item.get("missing_stages", [])],
        "events_missing_conflict": [item["event_id"] for item in candidates if "conflict" in item.get("missing_stages", [])],
        "events_missing_response": [item["event_id"] for item in candidates if "response" in item.get("missing_stages", [])],
        "events_with_all_core_stages": [
            item["event_id"]
            for item in candidates
            if not (CORE_STAGES & set(item.get("missing_stages", [])))
        ],
        "avg_evidence_per_stage": round(sum(avg_evidence_per_stage_values) / len(avg_evidence_per_stage_values), 4)
        if avg_evidence_per_stage_values
        else 0.0,
        "avg_event_relevance": round(
            sum(safe_float(diag.get("avg_event_relevance"), 0.0) for diag in diagnostics) / len(diagnostics), 4
        )
        if diagnostics
        else 0.0,
        "generic_penalty_count": sum(int(diag.get("generic_penalty_count", 0)) for diag in diagnostics),
        "deduplicated_evidence_count": sum(int(diag.get("deduplicated_evidence_count", 0)) for diag in diagnostics),
        "removed_duplicate_stage_assignments": sum(int(diag.get("removed_duplicate_stage_assignments", 0)) for diag in diagnostics),
        "output_path": output_path,
    }


def flatten_candidates(candidates: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for candidate in candidates:
        for stage in candidate.get("stages", []):
            for evidence in stage.get("evidence", []):
                rows.append(flatten_record(candidate["event_id"], stage, evidence))
    return rows


def audit_sample_rows(candidates: list[dict], per_stage: int = 20) -> list[dict]:
    rows = flatten_candidates(candidates)
    priority_events = {"E001", "E009", "E025"}
    selected: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for stage in STAGES:
        stage_rows = [row for row in rows if row["stage"] == stage]
        stage_rows.sort(
            key=lambda row: (
                row["event_id"] in priority_events,
                safe_float(row.get("final_stage_score"), 0.0),
            ),
            reverse=True,
        )
        for row in stage_rows[:per_stage]:
            key = (row["event_id"], row["stage"], row["evidence_id"])
            if key not in seen:
                selected.append(row)
                seen.add(key)
    for row in rows:
        if row["event_id"] in priority_events:
            key = (row["event_id"], row["stage"], row["evidence_id"])
            if key not in seen:
                selected.append(row)
                seen.add(key)
    return selected


def flatten_record(event_id: str, stage: dict, evidence: dict) -> dict:
    fields = {
        "event_id": event_id,
        "stage_order": stage.get("stage_order"),
        "stage": stage.get("stage"),
        "evidence_id": evidence.get("evidence_id"),
        "score": evidence.get("score"),
        "stage_score": evidence.get("stage_score"),
        "final_stage_score": evidence.get("final_stage_score"),
        "event_relevance_score": evidence.get("event_relevance_score"),
        "matched_event_terms": evidence.get("matched_event_terms", []),
        "matched_seed_keywords": evidence.get("matched_seed_keywords", []),
        "matched_event_name_terms": evidence.get("matched_event_name_terms", []),
        "matched_description_terms": evidence.get("matched_description_terms", []),
        "matched_stage_keywords": evidence.get("matched_stage_keywords", []),
        "generic_penalty_terms": evidence.get("generic_penalty_terms", []),
        "is_generic_penalized": evidence.get("is_generic_penalized", False),
        "stage_keyword_score": evidence.get("stage_keyword_score"),
        "quality_score_component": evidence.get("quality_score_component"),
        "source_prior_component": evidence.get("source_prior_component"),
        "stakeholder_signal_component": evidence.get("stakeholder_signal_component"),
        "source": evidence.get("source", ""),
        "domain": evidence.get("domain", ""),
        "url": evidence.get("url", ""),
        "title": evidence.get("title", ""),
        "text_excerpt": evidence.get("text_excerpt", ""),
    }
    for key, value in list(fields.items()):
        if isinstance(value, list):
            fields[key] = "|".join(str(item) for item in value)
    return fields


def retrieve_event_chains(events: list[EventRecord], evidence: list[EvidenceRecord], top_k: int = 5) -> list[dict]:
    event_rows = [event.model_dump() if hasattr(event, "model_dump") else dict(event) for event in events]
    evidence_rows = [row.model_dump() if hasattr(row, "model_dump") else dict(row) for row in evidence]
    return EventChainRetriever(top_k_per_stage=top_k).retrieve_all(event_rows, evidence_rows)


def extract_event_terms(text: str) -> list[str]:
    terms = []
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text):
        token = token.strip()
        if not token or token in EVENT_STOP_TERMS:
            continue
        if len(token) > 12:
            terms.extend(split_long_chinese_token(token))
        else:
            terms.append(token)
    return unique([term for term in terms if term and term not in EVENT_STOP_TERMS])


def is_event_specific_term(term: str) -> bool:
    if not term or term in EVENT_STOP_TERMS or len(term) < 2:
        return False
    return not any(generic in term for generic in GENERIC_TOPIC_TERMS)


def split_long_chinese_token(token: str) -> list[str]:
    chunks = []
    for size in (6, 5, 4):
        for idx in range(0, max(0, len(token) - size + 1)):
            piece = token[idx : idx + size]
            if piece not in EVENT_STOP_TERMS and not all(char in "，。；：、" for char in piece):
                chunks.append(piece)
    return chunks[:8]


def normalize_term_list(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    terms: list[str] = []
    for value in values:
        terms.extend(extract_event_terms(str(value)))
        raw = str(value).strip()
        if raw and len(raw) <= 20:
            terms.append(raw)
    return unique(terms)


def matched_terms(terms: list[str], text: str) -> list[str]:
    return unique([term for term in terms if term and term in text])


def weighted_match_score(terms: list[str], title: str, text: str, base_weight: float, cap: float) -> float:
    score = 0.0
    for term in terms:
        if term in title:
            score += base_weight * 1.35
        elif term in text:
            score += base_weight
    return min(cap, score)


def relevance_reason(score: float, event_id_match: bool, specific_terms: list[str], generic_only: bool, generic: dict) -> str:
    parts = []
    if event_id_match:
        parts.append("event_id_match")
    if specific_terms:
        parts.append("specific_terms")
    if generic_only:
        parts.append("generic_topic_only")
    if generic.get("is_generic"):
        parts.append("generic_policy_penalized")
    if not parts:
        parts.append("weak_or_no_event_match")
    return f"{','.join(parts)}; score={score:.4f}"


def stage_priority(stage: str) -> int:
    return DEDUP_STAGE_PRIORITY.index(stage) if stage in DEDUP_STAGE_PRIORITY else len(DEDUP_STAGE_PRIORITY)


def parse_time_sort_key(value: Any) -> float:
    parsed = parse_publish_time(value)
    return parsed.timestamp() if parsed else -math.inf


def parse_publish_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def text_excerpt(text: str, max_chars: int = 180) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    return compact[:max_chars]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def unique(values: list[Any]) -> list[Any]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
