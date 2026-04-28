"""Evidence support checks and verifier orchestration."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from episoa.llm.client import StructuredLLMClient
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.verifier.event_chain_consistency import event_chain_consistency_score
from episoa.verifier.sentiment_consistency import sentiment_consistency_score
from episoa.verifier.stakeholder_consistency import stakeholder_consistency_score


VERIFICATION_THRESHOLD = 0.75


class VerificationDecision(BaseModel):
    """Structured verifier output."""

    support_score: float = Field(..., ge=0.0, le=1.0)
    verified: bool
    failure_reason: str | None = None


class VerificationLLMClient(StructuredLLMClient, Protocol):
    """LLM client interface used by the verifier."""


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("-", " ").split() if token.strip()}


def evidence_support_score(
    attribution: AttributionTuple,
    evidence_records: list[EvidenceRecord],
) -> float:
    """Score whether evidence text supports the attribution content."""
    if not evidence_records:
        return 0.0

    claim_tokens = _tokens(
        " ".join(
            [
                attribution.event,
                attribution.stakeholder,
                attribution.opinion,
                attribution.rationale,
            ]
        )
    )
    if not claim_tokens:
        return 0.0

    per_record_scores: list[float] = []
    for evidence in evidence_records:
        evidence_tokens = _tokens(
            " ".join(
                [
                    evidence.text,
                    str(evidence.metadata.get("event", "")),
                    str(evidence.metadata.get("opinion", "")),
                    str(evidence.metadata.get("rationale", "")),
                ]
            )
        )
        if not evidence_tokens:
            per_record_scores.append(0.0)
            continue
        overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens)
        per_record_scores.append(min(1.0, overlap * 2.0))

    return sum(per_record_scores) / len(per_record_scores)


def verify_attribution(
    attribution: AttributionTuple,
    evidence_records: list[EvidenceRecord] | None = None,
    *,
    llm_client: VerificationLLMClient | None = None,
    threshold: float = VERIFICATION_THRESHOLD,
) -> AttributionTuple:
    """Return an AttributionTuple with updated support_score and verified fields."""
    evidence = evidence_records if evidence_records is not None else attribution.evidence
    support_score, failure_reason = _rule_based_verification(attribution, evidence, threshold)
    if llm_client is not None:
        prompt = build_verification_prompt(attribution, evidence, threshold)
        decision = VerificationDecision.model_validate(
            llm_client.generate_structured_verification(
                prompt,
                VerificationDecision,
                context={
                    "attribution": attribution,
                    "evidence_records": evidence,
                    "support_score": support_score,
                    "threshold": threshold,
                    "failure_reason": failure_reason,
                },
            )
        )
        return attribution.model_copy(
            update={
                "support_score": round(decision.support_score, 4),
                "verified": decision.verified,
                "failure_reason": decision.failure_reason if not decision.verified else None,
            }
        )

    verified = support_score >= threshold
    return attribution.model_copy(
        update={
            "support_score": support_score,
            "verified": verified,
            "failure_reason": None if verified else failure_reason,
        }
    )


def _rule_based_verification(
    attribution: AttributionTuple,
    evidence: list[EvidenceRecord],
    threshold: float,
) -> tuple[float, str | None]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    referenced_evidence = [
        evidence_by_id[item.evidence_id]
        for item in attribution.evidence
        if item.evidence_id in evidence_by_id
    ]
    if not referenced_evidence:
        referenced_evidence = evidence

    support = evidence_support_score(attribution, referenced_evidence)
    stakeholder = stakeholder_consistency_score(attribution, referenced_evidence)
    sentiment = sentiment_consistency_score(attribution, referenced_evidence)
    chain = event_chain_consistency_score(attribution, referenced_evidence)

    support_score = round(
        0.4 * support + 0.2 * stakeholder + 0.2 * sentiment + 0.2 * chain,
        4,
    )
    if support_score >= threshold:
        return support_score, None

    failed_checks: list[str] = []
    if support < threshold:
        failed_checks.append("evidence_support")
    if stakeholder < threshold:
        failed_checks.append("stakeholder_consistency")
    if sentiment < threshold:
        failed_checks.append("sentiment_consistency")
    if chain < threshold:
        failed_checks.append("event_chain_consistency")
    reason = "failed checks: " + ", ".join(failed_checks or ["support_score below threshold"])
    return support_score, reason


def build_verification_prompt(
    attribution: AttributionTuple,
    evidence_records: list[EvidenceRecord],
    threshold: float = VERIFICATION_THRESHOLD,
) -> str:
    """Build a strict JSON verifier prompt."""
    evidence_lines = "\n".join(
        (
            f"- evidence_id={item.evidence_id}; stakeholder={item.metadata.get('stakeholder') or item.author_alias}; "
            f"sentiment={item.metadata.get('sentiment') or item.metadata.get('stance') or 'unknown'}; "
            f"text={item.text}"
        )
        for item in evidence_records
    )
    return (
        "You are the Evidence Verifier for EpiSOA.\n"
        "Return JSON only. Do not include markdown or explanatory text.\n"
        "Return an object with exactly: support_score, verified, failure_reason.\n"
        f"Set verified=true only if support_score >= {threshold} and the evidence supports the tuple.\n"
        "Set failure_reason to null when verified=true; otherwise explain the failed check briefly.\n"
        f"Attribution tuple:\n{attribution.model_dump_json()}\n"
        f"Evidence:\n{evidence_lines}"
    )


def verify_attributions(
    attributions: list[AttributionTuple],
    evidence_records: list[EvidenceRecord],
    *,
    llm_client: VerificationLLMClient | None = None,
    threshold: float = VERIFICATION_THRESHOLD,
) -> list[AttributionTuple]:
    """Verify a batch of attribution tuples."""
    return [
        verify_attribution(attribution, evidence_records, llm_client=llm_client, threshold=threshold)
        for attribution in attributions
    ]
