from datetime import datetime, timezone

from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.verifier.evidence_support import verify_attribution


def make_evidence(
    evidence_id: str,
    text: str,
    stakeholder: str,
    sentiment: str,
    event: str,
) -> EvidenceRecord:
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
            "event": event,
            "opinion": text,
        },
    )


def make_attribution(evidence: list[EvidenceRecord]) -> AttributionTuple:
    return AttributionTuple(
        event="Policy change",
        stakeholder="Customers",
        opinion="Customers opposed the policy change.",
        sentiment="negative",
        rationale="Public criticism forced the policy change.",
        event_chain=["Public criticism", "Policy change"],
        evidence=evidence,
        support_score=0.0,
        verified=False,
    )


def test_supported_attribution_is_verified() -> None:
    evidence = [
        make_evidence(
            "ev-1",
            "Customers opposed the policy change after public criticism.",
            "Customers",
            "negative",
            "Policy change",
        )
    ]

    verified = verify_attribution(make_attribution(evidence), evidence)

    assert verified.verified is True
    assert verified.support_score >= 0.75


def test_unsupported_evidence_sets_verified_false() -> None:
    evidence = [
        make_evidence(
            "ev-1",
            "Employees supported an unrelated product launch.",
            "Employees",
            "positive",
            "Product launch",
        )
    ]

    verified = verify_attribution(make_attribution(evidence), evidence)

    assert verified.verified is False
    assert verified.support_score < 0.75


def test_file_based_verify_tuples_updates_support_label(tmp_path) -> None:
    from episoa.experimental_pipeline import verify_tuples

    tuples = tmp_path / "candidate.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    output = tmp_path / "verified.jsonl"
    tuples.write_text(
        AttributionTuple(
            event="Transit hearing",
            stakeholder="Riders",
            opinion="Riders opposed the fare increase.",
            sentiment="negative",
            rationale="Supported by evidence.",
            event_chain=["Transit hearing", "Riders"],
            evidence=[
                make_evidence(
                    "ev-1",
                    "Riders opposed the fare increase.",
                    "Riders",
                    "negative",
                    "Transit hearing",
                )
            ],
            support_score=0.8,
            verified=False,
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    evidence.write_text("", encoding="utf-8")

    assert verify_tuples(tuples, evidence, output) == 1
    assert '"verified":true' in output.read_text(encoding="utf-8")
