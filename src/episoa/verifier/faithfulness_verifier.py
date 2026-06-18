"""Faithfulness verifier for generated SOA tuples.

Checks whether evidence text actually supports each tuple's stakeholder+opinion claim.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verification.faithfulness_verifier import (
    VERIFIER_RESPONSE_FORMAT as DECOMPOSED_VERIFIER_RESPONSE_FORMAT,
    evidence_span_support,
    loose_contains,
    normalize_issue_flags as normalize_verifier_issue_flags,
    normalize_verification_diagnosis as normalize_script_verification_diagnosis,
    rule_precheck,
    support_level,
)


PIPELINE_VERIFIER_SCHEMA_VERSION = 2
HARD_PRECHECK_FLAGS = {
    "missing_evidence",
    "stakeholder_not_supported",
    "sentiment_not_supported",
    "rationale_not_supported",
    "evidence_span_not_supported",
    "stage_mismatch",
    "contradiction_detected",
}
SOFT_PRECHECK_FLAGS = {
    "weak_evidence",
    "opinion_overgeneralized",
    "media_comment_should_be_neutral",
    "official_action_should_be_neutral",
}


def verify_tuples(
    predictions: list[PredictionTuple],
    evidence: list[EvidenceRecord],
    threshold: float = 0.45,
    *,
    llm_client=None,
    mode: str = "decomposed",
    cache_dir: str | Path | None = None,
    max_api_concurrency: int = 1,
    chain_stages_by_event: dict[str, set[str]] | None = None,
) -> list[PredictionTuple]:
    """Verify prediction tuples against evidence.

    Without llm_client: checks only that evidence_ids exist in the evidence pool.
    With llm_client: also checks that evidence TEXT semantically supports the claim.
    """
    evidence_map = {item.evidence_id: item for item in evidence}
    cache_base = Path(cache_dir) / "verifier" if cache_dir is not None else None
    if cache_base is not None:
        cache_base.mkdir(parents=True, exist_ok=True)
    chain_stages = chain_stages_by_event or {}

    def verify_one(index: int, prediction: PredictionTuple) -> tuple[int, PredictionTuple]:
        missing = [eid for eid in prediction.evidence_ids if eid not in evidence_map]
        candidate = _prediction_to_candidate(prediction)
        evidence_items = [_evidence_to_dict(evidence_map[eid]) for eid in prediction.evidence_ids if eid in evidence_map]
        if mode == "id_only":
            precheck_flags = normalize_verifier_issue_flags(["missing_evidence"] if missing else [])
        else:
            precheck_flags = rule_precheck(
                candidate=candidate,
                evidence_items=evidence_items,
                missing_evidence_ids=missing,
                chain_stages_by_event=chain_stages,
            )
            precheck_flags = _relax_precheck_flags(
                precheck_flags, candidate, evidence_items, chain_stages
            )
        if missing:
            diagnosis = decomposed_diagnosis(
                prediction,
                evidence_map,
                score=0.0,
                missing_evidence_ids=missing,
                llm_details={},
                issue_flags=precheck_flags,
            )
            return index, (
                prediction.model_copy(
                    update={
                        "support_score": 0.0,
                        "verified": False,
                        "support_label": "insufficient_evidence",
                        "verification_diagnosis": diagnosis,
                    }
                )
            )

        # LLM-based verification of claim against evidence text
        if mode == "id_only":
            score = 1.0
            llm_details = {}
        elif llm_client is not None:
            key = verifier_cache_key(
                prediction,
                evidence_map,
                model_name=str(getattr(llm_client, "model_name", "")),
                base_url=str(getattr(llm_client, "base_url", "")),
                mode=mode,
                precheck_flags=precheck_flags,
            )
            cached = _read_verifier_cache(cache_base / f"{key}.json") if cache_base is not None else None
            if cached is None:
                score, llm_details = _llm_verify(prediction, evidence_map, llm_client)
                if cache_base is not None:
                    _write_verifier_cache(
                        cache_base / f"{key}.json",
                        {
                            "schema_version": PIPELINE_VERIFIER_SCHEMA_VERSION,
                            "cache_key": key,
                            "score": score,
                            "llm_details": llm_details,
                        },
                    )
                llm_details = dict(llm_details)
                llm_details["cache_hit"] = False
                llm_details["cache_key"] = key
            else:
                score = float(cached["score"])
                llm_details = dict(cached.get("llm_details", {}))
                llm_details["cache_hit"] = True
                llm_details["cache_key"] = key
        else:
            score = 1.0  # fallback: all evidence_ids exist
            llm_details = {}

        issue_flags = _merge_issue_flags(precheck_flags, llm_details)
        score = _apply_hard_flag_score_cap(score, issue_flags)
        diagnosis = decomposed_diagnosis(
            prediction,
            evidence_map,
            score=score,
            llm_details=llm_details,
            issue_flags=issue_flags,
        )
        if "cache_hit" in llm_details:
            diagnosis["cache_hit"] = llm_details["cache_hit"]
        if "cache_key" in llm_details:
            diagnosis["cache_key"] = llm_details["cache_key"]
        return index, (
            prediction.model_copy(
                update={
                    "support_score": score,
                    "verified": score >= threshold,
                    "support_label": _label_from_score(score, threshold),
                    "verification_diagnosis": diagnosis,
                }
            )
        )

    max_workers = max(1, int(max_api_concurrency or 1))
    if max_workers == 1 or len(predictions) <= 1:
        rows = [verify_one(index, prediction) for index, prediction in enumerate(predictions)]
    else:
        rows = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(verify_one, index, prediction) for index, prediction in enumerate(predictions)]
            for future in as_completed(futures):
                rows.append(future.result())
    return [row for _index, row in sorted(rows, key=lambda item: item[0])]


def verifier_cache_key(
    prediction: PredictionTuple,
    evidence_map: dict[str, EvidenceRecord],
    *,
    model_name: str,
    base_url: str,
    mode: str,
    precheck_flags: list[str] | None = None,
) -> str:
    payload = {
        "schema_version": PIPELINE_VERIFIER_SCHEMA_VERSION,
        "mode": mode,
        "model_name": model_name,
        "base_url": base_url,
        "verifier_system": VERIFIER_SYSTEM,
        "precheck_flags": normalize_verifier_issue_flags(precheck_flags or []),
        "tuple": {
            "tuple_id": getattr(prediction, "tuple_id", ""),
            "event_id": prediction.event_id,
            "stakeholder": prediction.stakeholder,
            "stakeholder_aliases": list(getattr(prediction, "stakeholder_aliases", []) or []),
            "opinion": prediction.opinion,
            "sentiment": prediction.sentiment,
            "rationale": prediction.rationale,
            "evidence_ids": list(prediction.evidence_ids),
            "event_chain_stage": prediction.event_chain_stage,
            "evidence_spans": list(prediction.evidence_spans or []),
        },
        "evidence": [
            {
                "evidence_id": eid,
                "event_id": evidence_map[eid].event_id,
                "text": evidence_map[eid].text,
            }
            for eid in prediction.evidence_ids
            if eid in evidence_map
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_verifier_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "score" not in payload:
        return None
    return payload


def _write_verifier_cache(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        # Cache is best-effort. Verification output should remain usable even
        # when the cache directory is locked or sandboxed.
        return


def _label_from_score(score: float, threshold: float) -> str:
    if score >= threshold:
        return "supported"
    elif score >= 0.4:
        return "partially_supported"
    return "insufficient_evidence"


def decomposed_diagnosis(
    prediction: PredictionTuple,
    evidence_map: dict[str, EvidenceRecord],
    *,
    score: float,
    missing_evidence_ids: list[str] | None = None,
    llm_details: dict | None = None,
    issue_flags: list[str] | None = None,
) -> dict:
    evidence_items = [evidence_map[eid] for eid in prediction.evidence_ids if eid in evidence_map]
    flags = normalize_verifier_issue_flags(issue_flags or [])
    payload = llm_details if isinstance(llm_details, dict) else {}
    diagnosis = normalize_script_verification_diagnosis(payload, flags=flags, score=score)
    evidence_same_event = bool(evidence_items) and all(item.event_id == prediction.event_id for item in evidence_items)
    if missing_evidence_ids:
        evidence_same_event = False
    if not evidence_same_event:
        diagnosis["evidence_same_event"] = False
    else:
        diagnosis.setdefault("evidence_same_event", True)
    diagnosis["missing_evidence_ids"] = missing_evidence_ids or []
    diagnosis["support_score"] = round(float(score), 4)
    diagnosis["issue_flags"] = flags
    if llm_details:
        if "reason" in llm_details:
            diagnosis["llm_reason"] = llm_details["reason"]
        if "verification_rationale" in llm_details:
            diagnosis["llm_reason"] = llm_details["verification_rationale"]
    return diagnosis


def _prediction_to_candidate(prediction: PredictionTuple) -> dict[str, Any]:
    return prediction.model_dump()


def _evidence_to_dict(evidence: EvidenceRecord) -> dict[str, Any]:
    return evidence.model_dump()


def _merge_issue_flags(precheck_flags: list[str], llm_details: dict | None) -> list[str]:
    flags: list[str] = list(precheck_flags or [])
    details = llm_details if isinstance(llm_details, dict) else {}
    raw_llm_flags = details.get("issue_flags", [])
    if isinstance(raw_llm_flags, str):
        flags.append(raw_llm_flags)
    elif isinstance(raw_llm_flags, list):
        flags.extend(str(flag) for flag in raw_llm_flags)
    diagnosis = details.get("verification_diagnosis") if isinstance(details.get("verification_diagnosis"), dict) else details
    if _diagnosis_false(diagnosis.get("stakeholder_support")):
        flags.append("stakeholder_not_supported")
    if _diagnosis_false(diagnosis.get("sentiment_support")):
        flags.append("sentiment_not_supported")
    if _diagnosis_false(diagnosis.get("rationale_support")):
        flags.append("rationale_not_supported")
    if _diagnosis_false(diagnosis.get("evidence_span_support")):
        flags.append("evidence_span_not_supported")
    if _diagnosis_false(diagnosis.get("temporal_stage_consistency")):
        flags.append("stage_mismatch")
    if diagnosis.get("contradiction_detected") is True or str(diagnosis.get("contradiction_detected", "")).lower() == "true":
        flags.append("contradiction_detected")
    return normalize_verifier_issue_flags(flags)


def _diagnosis_false(value: Any) -> bool:
    if value is False:
        return True
    return str(value).strip().lower() in {"false", "unsupported", "no"}


def _relax_precheck_flags(
    flags: list[str],
    candidate: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    chain_stages_by_event: dict[str, set[str]],
) -> list[str]:
    """Post-process rule_precheck flags to reduce over-rejection false positives.
    
    Only relaxes flags detected by rule_precheck (keyword-based heuristics).
    LLM-detected flags added later by _merge_issue_flags remain unaffected.
    
    Fix A: evidence_span_not_supported → char overlap ≥40% → remove flag
    Fix B: stage_mismatch → stage is a semantic variant of known stages → remove flag
    Fix C: contradiction_detected → <3 negative terms OR positive≥negative → remove flag
    Fix D: rationale_not_supported → ≥2 common CJK chars with evidence → remove flag
    """
    if not flags:
        return flags
    evidence_text = "\n".join(str(item.get("text", "")) for item in evidence_items)
    
    output = list(flags)
    
    # Fix A: relax evidence_span_not_supported via char overlap
    if "evidence_span_not_supported" in output:
        spans = candidate.get("evidence_spans", []) or []
        if _spans_char_overlap_ok(spans, evidence_text):
            output = [f for f in output if f != "evidence_span_not_supported"]
    
    # Fix B: relax stage_mismatch when stage is a variant of known stages
    if "stage_mismatch" in output:
        event_id = str(candidate.get("event_id", ""))
        stage = str(candidate.get("event_chain_stage", ""))
        known_stages = chain_stages_by_event.get(event_id, set())
        if known_stages and stage and _stage_is_variant(stage, known_stages):
            output = [f for f in output if f != "stage_mismatch"]
    
    # Fix C: relax contradiction_detected – require ≥3 negative signals
    # and negative must clearly outweigh positive
    if "contradiction_detected" in output:
        if not _contradiction_strong_enough(evidence_text):
            output = [f for f in output if f != "contradiction_detected"]
    
    # Fix D: relax rationale_not_supported via common character overlap
    if "rationale_not_supported" in output:
        rationale = str(candidate.get("rationale", ""))
        if rationale and _shared_chars_count(rationale, evidence_text) >= 2:
            output = [f for f in output if f != "rationale_not_supported"]
    
    return output


def _spans_char_overlap_ok(spans: list[dict], evidence_text: str) -> bool:
    """Check whether all evidence spans have ≥40% character overlap with evidence."""
    if not spans:
        return True
    for span in spans:
        if not isinstance(span, dict):
            return False
        text = str(span.get("text") or "").strip()
        if text and char_overlap(text, evidence_text) < 0.35:
            return False
    return True


_STAGE_VARIANT_GROUPS: list[set[str]] = [
    {"response", "resolution", "resolve", "答复", "回应", "解决", "处置", "处理", "处理结果", "反馈", "整改", "回应与处理"},
    {"trigger", "incident", "爆发", "触发", "发生", "事件", "起因"},
    {"diffusion", "spread", "扩散", "传播", "发酵", "舆情", "蔓延"},
    {"follow_up", "后续", "跟进", "跟踪", "后续发展", "持续影响"},
]


def _stage_is_variant(stage: str, known_stages: set[str]) -> bool:
    """Return True if stage is a semantic variant of any known stage."""
    stage_lower = stage.lower()
    for group in _STAGE_VARIANT_GROUPS:
        group_lower = {s.lower() for s in group}
        if stage_lower in group_lower:
            # Found which group this stage belongs to
            # Check if any known stage is also in this group
            if any(ks.lower() in group_lower for ks in known_stages):
                return True
    return False


def _contradiction_strong_enough(evidence_text: str) -> bool:
    """Return True only when contradiction evidence is strong enough to keep the flag.
    
    Keeps flag only when:
    - ≥3 distinct negative attitude terms are found, AND
    - Negative signals clearly outweigh positive signals (neg > pos).
    This prevents single negative terms in otherwise supportive evidence
    from triggering contradiction.
    """
    _NEG = ["反对", "质疑", "不满", "投诉", "举报", "抵触", "不同意", "难以接受", "担忧"]
    _POS = ["支持", "点赞", "满意", "认可", "感谢", "欢迎", "肯定", "赞扬", "好事", "益处", "有益", "同意", "赞同", "拥护", "批准", "签署"]
    
    neg_count = sum(1 for t in _NEG if t in evidence_text)
    pos_count = sum(1 for t in _POS if t in evidence_text)
    
    # Need ≥3 negative terms AND negative must outweigh positive
    return neg_count >= 3 and neg_count > pos_count


def _shared_chars_count(left: str, right: str) -> int:
    """Count unique CJK characters shared between two strings."""
    left_set = set(str(left or ""))
    right_set = set(str(right or ""))
    return len(left_set & right_set)


def _apply_hard_flag_score_cap(score: float, issue_flags: list[str]) -> float:
    if any(flag in HARD_PRECHECK_FLAGS for flag in issue_flags):
        score = min(score, 0.39)
    soft_count = sum(1 for flag in issue_flags if flag in SOFT_PRECHECK_FLAGS)
    if soft_count > 0:
        score = max(0.2, score - 0.1 * soft_count)
    return score


def char_overlap(left: str, right: str) -> float:
    left_chars = set(str(left or ""))
    right_chars = set(str(right or ""))
    if not left_chars or not right_chars:
        return 0.0
    return len(left_chars & right_chars) / len(left_chars | right_chars)


VERIFIER_SYSTEM = """你是严格的中文公共事件证据支撑度判定专家。判断证据是否直接支撑利益相关方的具体观点。

输出严格 JSON，包含 score/reason，也尽量给出 issue_flags 和 verification_diagnosis。

严格规则：
1. 证据必须同时满足两点才算支撑：(a) 明确提及该利益相关方或群体，(b) 明确表述或直接暗示该具体观点
2. 仅提及利益相关方但未涉及该观点 → score=0
3. 仅讨论相关话题但未明确支撑该具体主张 → score=0
4. 证据与观点无关或主题不同 → score=0
5. score=1.0仅当证据直接且完整支撑观点；score=0.5仅当部分支撑或需要推理；score=0.0当不支撑"""

VERIFIER_USER = """利益相关方：{stakeholder}
观点声明：{opinion}
情感倾向：{sentiment}

证据列表：
{evidence_texts}

请判定：这些证据是否支撑上述观点声明？输出 JSON：
{{
  "score": 0.0,
  "reason": "简要理由",
  "issue_flags": ["no_issue"],
  "verification_diagnosis": {{
    "stakeholder_support": true,
    "opinion_support": "supported|partial|unsupported|unclear",
    "sentiment_support": true,
    "rationale_support": true,
    "evidence_span_support": true,
    "temporal_stage_consistency": true,
    "over_inference": false,
    "contradiction_detected": false
  }}
}}"""


def _llm_verify(
    prediction: PredictionTuple,
    evidence_map: dict[str, EvidenceRecord],
    llm_client,
) -> tuple[float, dict]:
    """Use LLM to verify if evidence supports the tuple claim."""
    evidence_texts = []
    for eid in prediction.evidence_ids[:5]:  # max 5 evidence per check
        ev = evidence_map.get(eid)
        if ev:
            evidence_texts.append(f"[{eid}] {ev.text[:500]}")

    if not evidence_texts:
        return 0.0, {}

    user_prompt = VERIFIER_USER.format(
        stakeholder=prediction.stakeholder,
        opinion=prediction.opinion,
        sentiment=prediction.sentiment,
        evidence_texts="\n---\n".join(evidence_texts),
    )

    import json
    import re

    try:
        resp = llm_client.chat(
            system_prompt=VERIFIER_SYSTEM,
            user_prompt=user_prompt,
            response_format=DECOMPOSED_VERIFIER_RESPONSE_FORMAT,
        )
        content = resp.content.strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(m.group()) if m else {}
        score = float(parsed.get("score", parsed.get("verification_score", 0.5)))
        return score, parsed
    except Exception:
        return 0.5, {"reason": "llm_verifier_error"}  # conservative default on error
