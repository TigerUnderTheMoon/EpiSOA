from datetime import datetime, timezone

from episoa.reasoner.attribution_reasoner import AttributionReasoner, reason_attribution
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain


def make_evidence(evidence_id: str, stakeholder: str, sentiment: str, text: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        platform="Example",
        url=f"https://example.com/{evidence_id}",
        timestamp=datetime(2026, 4, 26, tzinfo=timezone.utc),
        text=text,
        author_alias=stakeholder,
        source_type="news",
        metadata={
            "stakeholder": stakeholder,
            "sentiment": sentiment,
            "opinion": text,
        },
    )


def make_event_chain(evidence: list[EvidenceRecord]) -> EventChain:
    return EventChain(
        target_event="Policy change",
        event_chain=["Public criticism", "Policy change"],
        stakeholders=["Customers"],
        candidate_rationales=["Public criticism preceded the policy change."],
        evidence=evidence,
    )


def test_attribution_output_json_can_be_parsed_by_schema() -> None:
    evidence = [
        make_evidence("ev-1", "Customers", "negative", "Customers opposed the policy change."),
        make_evidence("ev-2", "Customers", "negative", "Customers repeated concerns about the policy change."),
    ]

    tuples = reason_attribution(make_event_chain(evidence), evidence, "Policy change")
    payload = tuples[0].model_dump_json()
    parsed = AttributionTuple.model_validate_json(payload)

    assert parsed.stakeholder == "Customers"
    assert parsed.verified is True
    assert parsed.support_score == 1.0
    assert {item.evidence_id for item in parsed.evidence} == {"ev-1", "ev-2"}


def test_missing_or_insufficient_evidence_does_not_force_attribution() -> None:
    weak_evidence = [
        make_evidence("ev-1", "Customers", "negative", "Customers opposed the policy change."),
    ]

    weak_result = reason_attribution(make_event_chain(weak_evidence), weak_evidence, "Policy change")
    empty_result = reason_attribution(make_event_chain([]), [], "Policy change")

    assert weak_result[0].verified is False
    assert weak_result[0].rationale == "insufficient evidence"
    assert weak_result[0].support_score < 1.0
    assert empty_result == []


def test_llm_output_with_insufficient_evidence_is_not_marked_verified() -> None:
    weak_evidence = [
        make_evidence("ev-1", "Customers", "negative", "Customers opposed the policy change."),
    ]

    class OverconfidentClient:
        def generate_structured_attribution(self, prompt, schema, *, context=None):
            return [
                {
                    "event": "Policy change",
                    "stakeholder": "Customers",
                    "opinion": "Customers opposed the policy change.",
                    "sentiment": "negative",
                    "rationale": "Overconfident attribution.",
                    "event_chain": ["Public criticism", "Policy change"],
                    "evidence": weak_evidence,
                    "support_score": 1.0,
                    "verified": True,
                }
            ]

    result = AttributionReasoner(llm_client=OverconfidentClient()).reason(
        make_event_chain(weak_evidence),
        weak_evidence,
        "Policy change",
    )

    assert result[0].verified is False
    assert result[0].rationale == "insufficient evidence"
