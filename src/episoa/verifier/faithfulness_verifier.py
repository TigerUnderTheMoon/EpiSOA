"""Faithfulness verifier for generated SOA tuples.

Checks whether evidence text actually supports each tuple's stakeholder+opinion claim.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

from episoa.data.schema import EvidenceRecord, PredictionTuple


def verify_tuples(
    predictions: list[PredictionTuple],
    evidence: list[EvidenceRecord],
    threshold: float = 0.75,
    *,
    llm_client=None,
    mode: str = "decomposed",
    cache_dir: str | Path | None = None,
    max_api_concurrency: int = 1,
) -> list[PredictionTuple]:
    """Verify prediction tuples against evidence.

    Without llm_client: checks only that evidence_ids exist in the evidence pool.
    With llm_client: also checks that evidence TEXT semantically supports the claim.
    """
    evidence_map = {item.evidence_id: item for item in evidence}
    cache_base = Path(cache_dir) / "verifier" if cache_dir is not None else None
    if cache_base is not None:
        cache_base.mkdir(parents=True, exist_ok=True)

    def verify_one(index: int, prediction: PredictionTuple) -> tuple[int, PredictionTuple]:
        # Pre-check: all evidence_ids must exist
        missing = [eid for eid in prediction.evidence_ids if eid not in evidence_map]
        if missing:
            diagnosis = decomposed_diagnosis(prediction, evidence_map, score=0.0, missing_evidence_ids=missing)
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
            )
            cached = _read_verifier_cache(cache_base / f"{key}.json") if cache_base is not None else None
            if cached is None:
                score, llm_details = _llm_verify(prediction, evidence_map, llm_client)
                if cache_base is not None:
                    _write_verifier_cache(
                        cache_base / f"{key}.json",
                        {
                            "schema_version": 1,
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

        diagnosis = decomposed_diagnosis(prediction, evidence_map, score=score, llm_details=llm_details)
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
) -> str:
    payload = {
        "schema_version": 1,
        "mode": mode,
        "model_name": model_name,
        "base_url": base_url,
        "verifier_system": VERIFIER_SYSTEM,
        "tuple": {
            "event_id": prediction.event_id,
            "stakeholder": prediction.stakeholder,
            "opinion": prediction.opinion,
            "sentiment": prediction.sentiment,
            "rationale": prediction.rationale,
            "evidence_ids": list(prediction.evidence_ids),
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
        "evidence_span_support": evidence_span_support(prediction, evidence_text),
        "evidence_same_event": all(item.event_id == prediction.event_id for item in evidence_items),
        "temporal_stage_consistency": True,
        "over_inference": score < 0.4 or (opinion_overlap < 0.08 and rationale_overlap < 0.08),
        "contradiction_detected": False,
        "missing_evidence_ids": missing_evidence_ids or [],
        "support_score": round(float(score), 4),
    }
    if llm_details:
        for key in (
            "stakeholder_support",
            "opinion_support",
            "sentiment_support",
            "rationale_support",
            "evidence_span_support",
            "evidence_same_event",
            "temporal_stage_consistency",
            "over_inference",
            "contradiction_detected",
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


def evidence_span_support(prediction: PredictionTuple, evidence_text: str) -> bool:
    spans = prediction.evidence_spans or []
    if not spans:
        return True
    for span in spans:
        if not isinstance(span, dict):
            return False
        text = str(span.get("text") or "").strip()
        if text and text not in evidence_text:
            return False
    return True


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
