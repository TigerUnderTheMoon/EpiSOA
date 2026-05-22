from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verifier.faithfulness_verifier import verify_tuples


def test_pipeline_verifier_attaches_decomposed_diagnosis_without_llm():
    prediction = PredictionTuple(
        event_id="E1",
        stakeholder="Residents",
        opinion="complain about safety",
        sentiment="negative",
        rationale="Residents complain",
        evidence_ids=["ev1"],
        support_label="supported",
    )
    evidence = [
        EvidenceRecord(
            event_id="E1",
            evidence_id="ev1",
            source="news",
            text="Residents complain about safety conditions.",
        )
    ]

    verified = verify_tuples([prediction], evidence, mode="decomposed")

    assert verified[0].verified is True
    assert verified[0].verification_diagnosis["evidence_same_event"] is True
    assert verified[0].verification_diagnosis["opinion_support"] == "supported"


def test_pipeline_verifier_id_only_skips_llm_and_marks_missing_evidence():
    prediction = PredictionTuple(
        event_id="E1",
        stakeholder="Residents",
        opinion="complain",
        sentiment="negative",
        rationale="missing evidence",
        evidence_ids=["missing"],
        support_label="supported",
    )

    verified = verify_tuples([prediction], [], llm_client=object(), mode="id_only")

    assert verified[0].verified is False
    assert verified[0].support_label == "insufficient_evidence"
    assert verified[0].verification_diagnosis["missing_evidence_ids"] == ["missing"]
