"""Schema-constrained attribution reasoning."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import TypeAdapter

from episoa.llm.client import LLMClient, StructuredLLMClient
from episoa.schemas.attribution import AttributionTuple, SentimentLabel
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain


class AttributionLLMClient(StructuredLLMClient, Protocol):
    """Replaceable structured generation interface for future LLM clients."""


AttributionTupleList = TypeAdapter(list[AttributionTuple])


class RuleBasedAttributionLLMClient(LLMClient):
    """Backward-compatible mock LLM client alias."""

    def __init__(self) -> None:
        super().__init__({"mode": "mock"})


class AttributionReasoner:
    """Reason over event chains and evidence to produce validated attribution tuples."""

    def __init__(self, llm_client: AttributionLLMClient | None = None, min_evidence_for_verified: int = 2) -> None:
        self.llm_client = llm_client
        self.min_evidence_for_verified = min_evidence_for_verified

    def reason(
        self,
        event_chain: EventChain,
        evidence_records: list[EvidenceRecord],
        target_event_description: str,
    ) -> list[AttributionTuple]:
        """Produce schema-validated attribution tuples."""
        if not evidence_records:
            return []

        if self.llm_client is not None:
            prompt = build_attribution_prompt(event_chain, evidence_records, target_event_description)
            raw_output = self.llm_client.generate_structured_attribution(
                prompt,
                list[AttributionTuple],
                context={
                    "event_chain": event_chain,
                    "evidence_records": evidence_records,
                    "target_event_description": target_event_description,
                    "min_evidence_for_verified": self.min_evidence_for_verified,
                },
            )
            tuples = AttributionTupleList.validate_python(raw_output)
            return self._enforce_evidence_policy(tuples)

        raw_output = self._mock_attribution(event_chain, evidence_records, target_event_description)
        tuples = AttributionTupleList.validate_python(raw_output)
        return self._enforce_evidence_policy(tuples)

    def _enforce_evidence_policy(self, tuples: list[AttributionTuple]) -> list[AttributionTuple]:
        """Ensure insufficient evidence is never marked as verified."""
        normalized: list[AttributionTuple] = []
        for item in tuples:
            if len(item.evidence) < self.min_evidence_for_verified:
                rationale = item.rationale
                if item.verified:
                    rationale = "insufficient evidence"
                normalized.append(
                    item.model_copy(
                        update={
                            "verified": False,
                            "rationale": rationale,
                            "support_score": min(
                                item.support_score,
                                _support_score(item.evidence, self.min_evidence_for_verified),
                            ),
                        }
                    )
                )
            else:
                normalized.append(item)
        return normalized

    def _mock_attribution(
        self,
        event_chain: EventChain,
        evidence_records: list[EvidenceRecord],
        target_event_description: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[EvidenceRecord]] = {}
        for evidence in evidence_records:
            stakeholder = _stakeholder_for(evidence)
            grouped.setdefault(stakeholder, []).append(evidence)

        output: list[dict[str, Any]] = []
        for stakeholder, stakeholder_evidence in grouped.items():
            verified = len(stakeholder_evidence) >= self.min_evidence_for_verified
            output.append(
                {
                    "event": target_event_description.strip() or event_chain.target_event,
                    "stakeholder": stakeholder,
                    "opinion": _opinion_for(stakeholder_evidence),
                    "sentiment": _sentiment_for(stakeholder_evidence),
                    "rationale": _rationale_for(stakeholder_evidence, verified),
                    "event_chain": event_chain.event_chain,
                    "evidence": stakeholder_evidence,
                    "support_score": _support_score(stakeholder_evidence, self.min_evidence_for_verified),
                    "verified": verified,
                }
            )

        return output


def build_attribution_prompt(
    event_chain: EventChain,
    evidence_records: list[EvidenceRecord],
    target_event_description: str,
) -> str:
    """Build a compact prompt for schema-constrained LLM attribution."""
    evidence_lines = "\n".join(
        (
            f"- evidence_id={item.evidence_id}; platform={item.platform}; url={item.url}; "
            f"timestamp={item.timestamp.isoformat()}; stakeholder={_stakeholder_for(item)}; "
            f"sentiment_hint={item.metadata.get('sentiment') or item.metadata.get('stance') or 'unknown'}; "
            f"text={item.text}"
        )
        for item in evidence_records
    )
    return (
        "You are the Schema-constrained Attribution Reasoner for EpiSOA.\n"
        "Return JSON only. Do not include markdown, comments, or explanatory text.\n"
        "Return a JSON object with one key, attributions, whose value is an array of AttributionTuple items.\n"
        "Each tuple must cite only evidence records supplied below.\n"
        "If the supplied evidence is insufficient for an attribution, set verified=false "
        'or set rationale to "insufficient evidence".\n'
        "Use sentiment as one of: positive, negative, neutral, mixed, unknown.\n"
        f"Target event: {target_event_description}\n"
        f"Event chain: {' -> '.join(event_chain.event_chain)}\n"
        f"Evidence:\n{evidence_lines}"
    )


def reason_attribution(
    event_chain: EventChain,
    evidence_records: list[EvidenceRecord],
    target_event_description: str,
    llm_client: AttributionLLMClient | None = None,
) -> list[AttributionTuple]:
    """Convenience function for attribution reasoning."""
    return AttributionReasoner(llm_client=llm_client).reason(
        event_chain,
        evidence_records,
        target_event_description,
    )


def _stakeholder_for(evidence: EvidenceRecord) -> str:
    value = evidence.metadata.get("stakeholder") or evidence.author_alias or "unknown"
    return str(value).strip() or "unknown"


def _opinion_for(evidence_records: list[EvidenceRecord]) -> str:
    explicit_opinions = [
        str(item.metadata["opinion"]).strip()
        for item in evidence_records
        if item.metadata.get("opinion") and str(item.metadata["opinion"]).strip()
    ]
    if explicit_opinions:
        return explicit_opinions[0]
    return evidence_records[0].text


def _sentiment_for(evidence_records: list[EvidenceRecord]) -> SentimentLabel:
    allowed = {"positive", "negative", "neutral", "mixed", "unknown"}
    sentiments = [
        str(item.metadata.get("sentiment") or item.metadata.get("stance") or "unknown").strip().lower()
        for item in evidence_records
    ]
    valid_sentiments = [item for item in sentiments if item in allowed]
    if not valid_sentiments:
        return "unknown"
    if len(set(valid_sentiments)) > 1:
        return "mixed"
    return valid_sentiments[0]  # type: ignore[return-value]


def _rationale_for(evidence_records: list[EvidenceRecord], verified: bool) -> str:
    if not verified:
        return "insufficient evidence"
    rationale = evidence_records[0].metadata.get("rationale")
    if rationale and str(rationale).strip():
        return str(rationale).strip()
    evidence_ids = ", ".join(item.evidence_id for item in evidence_records)
    return f"Supported by evidence records: {evidence_ids}"


def _support_score(evidence_records: list[EvidenceRecord], min_evidence_for_verified: int) -> float:
    if min_evidence_for_verified <= 0:
        return 1.0
    return min(1.0, len(evidence_records) / min_evidence_for_verified)
