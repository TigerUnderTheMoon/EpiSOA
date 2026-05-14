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
            verified.append(
                prediction.model_copy(
                    update={
                        "support_score": 0.0,
                        "verified": False,
                        "support_label": "insufficient_evidence",
                    }
                )
            )
            continue

        # LLM-based verification of claim against evidence text
        if llm_client is not None:
            score = _llm_verify(prediction, evidence_map, llm_client)
        else:
            score = 1.0  # fallback: all evidence_ids exist

        verified.append(
            prediction.model_copy(
                update={
                    "support_score": score,
                    "verified": score >= threshold,
                    "support_label": _label_from_score(score, threshold),
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
) -> float:
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
        return float(parsed.get("score", 0.5))
    except Exception:
        return 0.5  # conservative default on error
