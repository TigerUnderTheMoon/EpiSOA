import json

from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verifier.faithfulness_verifier import verify_tuples


class FakeDecomposedVerifierClient:
    model_name = "fake-model"
    base_url = "https://fake.test/v1"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return type(
            "Response",
            (),
            {
                "content": json.dumps(self.payload, ensure_ascii=False),
                "response_id": f"fake-{self.calls}",
                "raw": {},
            },
        )()


def prediction(**overrides) -> PredictionTuple:
    row = {
        "event_id": "E001",
        "stakeholder": "住建部门",
        "opinion": "住建部门回应居民诉求并推进整改",
        "sentiment": "neutral",
        "rationale": "住建局回应居民诉求",
        "evidence_ids": ["ev-001"],
        "support_label": "supported",
        "event_chain_stage": "response",
    }
    row.update(overrides)
    return PredictionTuple(**row)


def evidence(text: str, **overrides) -> EvidenceRecord:
    row = {
        "event_id": "E001",
        "evidence_id": "ev-001",
        "source": "official",
        "text": text,
    }
    row.update(overrides)
    return EvidenceRecord(**row)


def test_pipeline_verifier_attaches_decomposed_diagnosis_without_llm():
    prediction_row = PredictionTuple(
        event_id="E1",
        stakeholder="Residents",
        opinion="complain about safety",
        sentiment="negative",
        rationale="Residents complain",
        evidence_ids=["ev1"],
        support_label="supported",
    )
    evidence_rows = [
        EvidenceRecord(
            event_id="E1",
            evidence_id="ev1",
            source="news",
            text="Residents complain about safety conditions.",
        )
    ]

    verified = verify_tuples([prediction_row], evidence_rows, mode="decomposed")

    assert verified[0].verified is True
    assert verified[0].verification_diagnosis["evidence_same_event"] is True
    assert verified[0].verification_diagnosis["opinion_support"] == "supported"


def test_pipeline_verifier_id_only_skips_llm_and_marks_missing_evidence():
    prediction_row = PredictionTuple(
        event_id="E1",
        stakeholder="Residents",
        opinion="complain",
        sentiment="negative",
        rationale="missing evidence",
        evidence_ids=["missing"],
        support_label="supported",
    )

    verified = verify_tuples([prediction_row], [], llm_client=object(), mode="id_only")

    assert verified[0].verified is False
    assert verified[0].support_label == "insufficient_evidence"
    assert verified[0].verification_diagnosis["missing_evidence_ids"] == ["missing"]


def test_pipeline_verifier_precheck_blocks_unsupported_positive_sentiment_without_llm():
    verified = verify_tuples(
        [
            prediction(
                stakeholder="住建部门",
                opinion="住建部门发布整改通告",
                sentiment="positive",
                rationale="住建部门发布整改通告",
            )
        ],
        [evidence("住建部门发布通告称将开展整改。")],
        mode="decomposed",
    )

    diagnosis = verified[0].verification_diagnosis
    assert verified[0].verified is False
    assert diagnosis["sentiment_support"] is False
    assert "sentiment_not_supported" in diagnosis["issue_flags"]


def test_pipeline_verifier_uses_chain_stages_for_temporal_consistency():
    verified = verify_tuples(
        [prediction(event_chain_stage="trigger")],
        [evidence("住建部门回应居民诉求并说明整改安排。")],
        mode="decomposed",
        chain_stages_by_event={"E001": {"response"}},
    )

    diagnosis = verified[0].verification_diagnosis
    assert diagnosis["temporal_stage_consistency"] is False
    assert "stage_mismatch" in diagnosis["issue_flags"]
    # A lone stage_mismatch with all content fields supported is downgraded to a
    # soft penalty (not the hard 0.39 cap), so the tuple stays verified. This
    # avoids over-rejecting tuples whose content is fully evidence-grounded but
    # whose event-chain stage label is a near-miss variant.
    assert verified[0].verified is True


def test_pipeline_verifier_stage_mismatch_still_caps_when_content_unsupported():
    """When stage_mismatch co-occurs with a content-faithfulness hard flag
    (e.g. rationale_not_supported), the hard cap still applies."""
    client = FakeDecomposedVerifierClient(
        {
            "score": 0.9,
            "reason": "rationale not grounded",
            "verification_diagnosis": {
                "stakeholder_support": True,
                "opinion_support": "supported",
                "sentiment_support": True,
                "rationale_support": False,
                "evidence_span_support": True,
                "temporal_stage_consistency": False,
            },
        }
    )
    verified = verify_tuples(
        [prediction(event_chain_stage="trigger")],
        [evidence("住建部门回应居民诉求并说明整改安排。")],
        mode="decomposed",
        chain_stages_by_event={"E001": {"response"}},
        llm_client=client,
    )
    diagnosis = verified[0].verification_diagnosis
    assert "stage_mismatch" in diagnosis["issue_flags"]
    assert "rationale_not_supported" in diagnosis["issue_flags"]
    assert verified[0].verified is False


def test_pipeline_verifier_preserves_llm_nested_contradiction_diagnosis():
    client = FakeDecomposedVerifierClient(
        {
            "score": 0.9,
            "reason": "LLM found contradiction",
            "verification_diagnosis": {
                "contradiction_detected": True,
                "sentiment_support": True,
            },
        }
    )

    verified = verify_tuples(
        [prediction()],
        [evidence("住建部门回应居民诉求并说明整改安排。")],
        llm_client=client,
        mode="decomposed",
    )

    assert client.calls == 1
    assert verified[0].verification_diagnosis["contradiction_detected"] is True
    assert verified[0].verified is False


def test_pipeline_verifier_uses_candidate_stakeholder_aliases():
    verified = verify_tuples(
        [
            prediction(
                stakeholder="住房城乡建设部门",
                stakeholder_aliases=["住建局"],
                opinion="住建局回应居民诉求",
                rationale="住建局回应居民诉求",
            )
        ],
        [evidence("住建局回应居民诉求并说明整改安排。")],
        mode="decomposed",
    )

    assert verified[0].verification_diagnosis["stakeholder_support"] is True
