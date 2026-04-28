from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evaluation import EvaluationSample, MetricScore
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain


def make_evidence() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="ev-001",
        platform="Example News",
        url="https://example.com/article",
        timestamp=datetime(2026, 4, 26, tzinfo=timezone.utc),
        text="Company A announced a policy change after public criticism.",
        author_alias="reporter",
        source_type="news",
        metadata={"language": "en"},
    )


def test_evidence_record_accepts_valid_data() -> None:
    evidence = make_evidence()

    assert evidence.evidence_id == "ev-001"
    assert str(evidence.url) == "https://example.com/article"
    assert evidence.metadata["language"] == "en"


def test_evidence_record_rejects_blank_text_and_bad_url() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="ev-001",
            platform="Example News",
            url="not-a-url",
            timestamp=datetime.now(timezone.utc),
            text=" ",
            author_alias=None,
            source_type="news",
            metadata={},
        )


def test_event_chain_requires_non_empty_chain_and_stakeholders() -> None:
    chain = EventChain(
        target_event="Policy change",
        event_chain=["Public criticism", "Company response"],
        stakeholders=["Company A", "Customers"],
        candidate_rationales=["The response followed sustained criticism."],
        evidence=[make_evidence()],
    )

    assert chain.event_chain == ["Public criticism", "Company response"]
    assert chain.evidence[0].evidence_id == "ev-001"


def test_event_chain_rejects_blank_items() -> None:
    with pytest.raises(ValidationError):
        EventChain(
            target_event="Policy change",
            event_chain=["Public criticism", ""],
            stakeholders=["Customers"],
        )


def test_attribution_tuple_validates_score_and_sentiment() -> None:
    tuple_ = AttributionTuple(
        event="Policy change",
        stakeholder="Customers",
        opinion="The change was necessary.",
        sentiment="positive",
        rationale="The opinion is directly stated in collected evidence.",
        event_chain=["Public criticism", "Company response"],
        evidence=[make_evidence()],
        support_score=0.82,
        verified=True,
    )

    assert tuple_.support_score == 0.82
    assert tuple_.verified is True


def test_attribution_tuple_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        AttributionTuple(
            event="Policy change",
            stakeholder="Customers",
            opinion="The change was necessary.",
            sentiment="positive",
            rationale="Supported by evidence.",
            event_chain=["Public criticism"],
            evidence=[make_evidence()],
            support_score=1.5,
            verified=False,
        )


def test_evaluation_schemas_accept_valid_scores() -> None:
    metric = MetricScore(name="tuple_f1", value=0.75, details={"split": "dev"})
    sample = EvaluationSample(sample_id="sample-001", query="Why did the policy change?")

    assert metric.name == "tuple_f1"
    assert sample.expected == []
    assert sample.predicted == []


def test_metric_score_rejects_invalid_value() -> None:
    with pytest.raises(ValidationError):
        MetricScore(name="tuple_f1", value=-0.1)
