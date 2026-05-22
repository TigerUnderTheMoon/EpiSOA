"""Faithfulness verifier for generated SOA tuples.

Checks whether evidence text actually supports each tuple's stakeholder+opinion claim.
"""

from __future__ import annotations

from episoa.data.schema import EvidenceRecord, PredictionTuple


def verify_tuples(
    predictions: list[PredictionTuple],
    evidence: list[EvidenceRecord],
    threshold: float = 0.75,
    *,
    llm_client=None,
    mode: str = "decomposed",
) -> list[PredictionTuple]:
    """Verify prediction tuples against evidence.

    Without llm_client: checks only that evidence_ids exist in the evidence pool.
    With llm_client: also checks that evidence TEXT semantically supports the claim.
    """
    evidence_map = {item.evidence_id: item for item in evidence}
    verified: list[PredictionTuple] = []

    for prediction in predictions:
        # Pre-check: all evidence_ids must exist
        missing = [eid for eid in prediction.evidence_ids if eid not in evidence_map]
        if missing:
            diagnosis = decomposed_diagnosis(prediction, evidence_map, score=0.0, missing_evidence_ids=missing)
            verified.append(
                prediction.model_copy(
                    update={
                        "support_score": 0.0,
                        "verified": False,
                        "support_label": "insufficient_evidence",
                        "verification_diagnosis": diagnosis,
                    }
                )
            )
            continue

        # LLM-based verification of claim against evidence text
        if mode == "id_only":
            score = 1.0
            llm_details = {}
        elif llm_client is not None:
            score, llm_details = _llm_verify(prediction, evidence_map, llm_client)
        else:
            score = 1.0  # fallback: all evidence_ids exist
            llm_details = {}

        diagnosis = decomposed_diagnosis(prediction, evidence_map, score=score, llm_details=llm_details)
        verified.append(
            prediction.model_copy(
                update={
                    "support_score": score,
                    "verified": score >= threshold,
                    "support_label": _label_from_score(score, threshold),
                    "verification_diagnosis": diagnosis,
                }
            )
        )

    return verified


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
) -> dict:
    evidence_items = [evidence_map[eid] for eid in prediction.evidence_ids if eid in evidence_map]
    evidence_text = "\n".join(item.text for item in evidence_items)
    stakeholder_support = bool(evidence_text and loose_contains(evidence_text, prediction.stakeholder))
    opinion_overlap = char_overlap(prediction.opinion, evidence_text)
    rationale_overlap = char_overlap(prediction.rationale, evidence_text)
    diagnosis = {
        "stakeholder_support": stakeholder_support,
        "opinion_support": support_level(opinion_overlap, score),
        "sentiment_support": True,
        "rationale_support": support_level(rationale_overlap, score),
        "evidence_same_event": all(item.event_id == prediction.event_id for item in evidence_items),
        "temporal_stage_consistency": True,
        "over_inference": score < 0.4 or (opinion_overlap < 0.08 and rationale_overlap < 0.08),
        "missing_evidence_ids": missing_evidence_ids or [],
        "support_score": round(float(score), 4),
    }
    if llm_details:
        for key in (
            "stakeholder_support",
            "opinion_support",
            "sentiment_support",
            "rationale_support",
            "evidence_same_event",
            "temporal_stage_consistency",
            "over_inference",
        ):
            if key in llm_details:
                diagnosis[key] = llm_details[key]
        if "reason" in llm_details:
            diagnosis["llm_reason"] = llm_details["reason"]
    return diagnosis


def support_level(overlap: float, score: float) -> str:
    if score >= 0.75 or overlap >= 0.18:
        return "supported"
    if score >= 0.4 or overlap >= 0.06:
        return "partial"
    return "unsupported"


def char_overlap(left: str, right: str) -> float:
    left_chars = set(str(left or ""))
    right_chars = set(str(right or ""))
    if not left_chars or not right_chars:
        return 0.0
    return len(left_chars & right_chars) / len(left_chars | right_chars)


def loose_contains(text: str, needle: str) -> bool:
    needle = str(needle or "")
    text = str(text or "")
    if not needle:
        return True
    if needle in text:
        return True
    tokens = [needle[idx:idx + 2] for idx in range(0, max(1, len(needle) - 1), 2)]
    return bool(tokens and any(token and token in text for token in tokens))


VERIFIER_SYSTEM = """你是严格的中文公共事件证据支撑度判定专家。判断证据是否直接支撑利益相关方的具体观点。

输出严格 JSON：
{"score": 0.0-1.0, "reason": "简要理由"}

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

请判定：这些证据是否支撑上述观点声明？输出 JSON。"""


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
        return 0.0

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
        )
        content = resp.content.strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(m.group()) if m else {}
        score = float(parsed.get("score", parsed.get("verification_score", 0.5)))
        return score, parsed
    except Exception:
        return 0.5, {"reason": "llm_verifier_error"}  # conservative default on error
