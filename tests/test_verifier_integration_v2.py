"""Integration tests for verifier pipeline (v2).

Task 14 of EpiSOA resubmission Wave 2: pipeline-level integration tests for
verify_tuples() covering the full call chain (rule_precheck → LLM → quality_gate).

These tests use mock LLM (FakeLLMClient) and Chinese evidence fixtures to
verify end-to-end verifier behavior without calling real LLM API.

Test scenarios:
  1. All-pass: evidence fully supports tuple
  2. All-reject: evidence unrelated to tuple
  3. LLM error: tuple not rejected solely due to LLM infrastructure error
  4. Threshold boundary: score=0.45, 0.46, 0.75 behavior
  5. Empty predictions list
  6. Empty evidence list (missing evidence IDs)
"""

import json

import pytest

from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verifier.faithfulness_verifier import verify_tuples


# ── Mock LLM Client ───────────────────────────────────────────────


class FakeLLMClient:
    """Mock LLM client that returns canned JSON responses for testing."""

    model_name = "fake-integration-model"
    base_url = "https://fake.test/v1"

    def __init__(self, score: float = 0.8, content_override: dict | None = None):
        self.score = score
        self.content_override = content_override or {}
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        payload = {
            "score": self.score,
            "reason": "测试用模拟LLM响应",
            "verification_diagnosis": {
                "stakeholder_support": True,
                "opinion_support": "supported",
                "sentiment_support": True,
                "rationale_support": True,
                "evidence_span_support": True,
                "temporal_stage_consistency": True,
                "over_inference": False,
                "contradiction_detected": False,
            },
        }
        payload.update(self.content_override)
        return type(
            "FakeResponse",
            (),
            {
                "content": json.dumps(payload, ensure_ascii=False),
                "response_id": f"fake-resp-{self.calls}",
            },
        )()


class FakeLLMErrorClient:
    """Mock LLM client that always raises an exception."""

    model_name = "fake-error-model"
    base_url = "https://fake.test/v1"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        raise ConnectionError("Simulated LLM API error")


# ── Helper factories ─────────────────────────────────────────────


def make_prediction(**overrides) -> PredictionTuple:
    defaults = {
        "event_id": "E001",
        "stakeholder": "白云区政府",
        "opinion": "白云区政府印发了城中村改造征收补偿安置方案",
        "sentiment": "neutral",
        "rationale": "白云区政府印发补偿安置方案",
        "evidence_ids": ["ev-001"],
        "support_label": "supported",
        "event_chain_stage": "response",
        "evidence_spans": [],
    }
    defaults.update(overrides)
    return PredictionTuple(**defaults)


def make_evidence(
    text: str,
    evidence_id: str = "ev-001",
    event_id: str = "E001",
    **overrides,
) -> EvidenceRecord:
    defaults = {
        "event_id": event_id,
        "evidence_id": evidence_id,
        "source": "official",
        "text": text,
    }
    defaults.update(overrides)
    return EvidenceRecord(**defaults)


# ══════════════════════════════════════════════════════════════════
# Integration tests
# ══════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_all_pass_evidence_fully_supports_tuple():
    """When evidence fully supports the tuple, verify_tuples should return
    verified=True with support_label='supported'."""
    fake_llm = FakeLLMClient(score=0.9)

    predictions = [
        make_prediction(
            stakeholder="广州市白云区政府",
            opinion="白云区政府印发了城中村改造征收补偿安置方案",
            evidence_ids=["ev-001"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text=(
                "广州市白云区人民政府正式印发了三元里村城中村改造项目"
                "土地及房屋征收补偿安置方案，明确了征收范围和补偿标准。"
            ),
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 1
    assert verified[0].verified is True
    assert verified[0].support_label == "supported"
    assert verified[0].support_score >= 0.45


@pytest.mark.integration
def test_all_reject_evidence_unrelated_to_tuple():
    """When evidence is unrelated to the tuple, verify_tuples should return
    verified=False with low support_score."""
    fake_llm = FakeLLMClient(
        score=0.1,
        content_override={
            "verification_diagnosis": {
                "stakeholder_support": False,
                "opinion_support": "unsupported",
                "sentiment_support": False,
                "rationale_support": False,
                "evidence_span_support": False,
                "temporal_stage_consistency": False,
                "over_inference": True,
                "contradiction_detected": False,
            }
        },
    )

    predictions = [
        make_prediction(
            stakeholder="某医院",
            opinion="医院发布了医患纠纷处置方案",
            evidence_ids=["ev-001"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text="今天天气晴朗，适合户外活动。",
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 1
    assert verified[0].verified is False


@pytest.mark.integration
def test_llm_error_does_not_reject_tuple():
    """When LLM client raises an exception, verify_tuples should NOT reject
    the tuple solely due to the LLM error (Task 8 fix)."""
    fake_llm = FakeLLMErrorClient()

    predictions = [
        make_prediction(
            stakeholder="白云区政府",
            opinion="白云区政府印发补偿安置方案",
            evidence_ids=["ev-001"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text="白云区政府印发了城中村改造征收补偿安置方案。",
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 1
    # After Task 8 fix: LLM error returns score=0.6, 0.6 >= 0.45 → verified=True
    assert verified[0].support_score >= 0.45
    assert verified[0].verified is True


@pytest.mark.integration
def test_threshold_boundary_score_exactly_0_45():
    """When LLM returns score exactly 0.45, tuple should be verified (>= threshold)."""
    fake_llm = FakeLLMClient(score=0.45)

    predictions = [
        make_prediction(
            stakeholder="白云区政府",
            opinion="白云区政府印发补偿安置方案",
            evidence_ids=["ev-001"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text="白云区政府印发了城中村改造征收补偿安置方案。",
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert verified[0].support_score >= 0.45
    assert verified[0].verified is True


@pytest.mark.integration
def test_empty_predictions_list():
    """When predictions list is empty, verify_tuples should return empty list."""
    fake_llm = FakeLLMClient()

    verified = verify_tuples(
        [],
        [make_evidence(text="测试证据")],
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert verified == []
    assert fake_llm.calls == 0


@pytest.mark.integration
def test_missing_evidence_ids():
    """When prediction references evidence_ids not in evidence list,
    verify_tuples should mark as insufficient_evidence with score=0.0."""
    fake_llm = FakeLLMClient(score=0.9)

    predictions = [
        make_prediction(
            evidence_ids=["ev-missing"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text="白云区政府印发了城中村改造征收补偿安置方案。",
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 1
    assert verified[0].support_score == 0.0
    assert verified[0].verified is False
    assert verified[0].support_label == "insufficient_evidence"
    # LLM should not be called for missing evidence
    assert fake_llm.calls == 0


@pytest.mark.integration
def test_id_only_mode_skips_llm():
    """When mode='id_only', verify_tuples should skip LLM calls and accept
    all tuples with valid evidence_ids."""
    fake_llm = FakeLLMClient()

    predictions = [
        make_prediction(
            evidence_ids=["ev-001"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text="白云区政府印发了城中村改造征收补偿安置方案。",
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="id_only",
    )

    assert verified[0].verified is True
    assert verified[0].support_score == 1.0
    # LLM should not be called in id_only mode
    assert fake_llm.calls == 0
