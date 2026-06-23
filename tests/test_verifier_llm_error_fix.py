"""TDD RED-phase tests for verifier LLM error fallback bug.

Task 2 of EpiSOA resubmission Wave 1: capture LLM error fallback over-rejection.
These tests MUST FAIL with current code (RED phase). They will be used in
Wave 2 Task 8 to verify the fix (GREEN phase).

Bug location: src/episoa/verifier/faithfulness_verifier.py:596
    except Exception:
        return 0.5, {"reason": "llm_verifier_error"}  # BUG: 0.5 < 0.75 → all rejected

Current behavior: When LLM client raises any exception (network timeout, JSON
parse failure, API rate limit), _llm_verify() returns score=0.5. Since 0.5 is
below the config threshold of 0.75, ALL error-case tuples are rejected.

Expected behavior (after GREEN fix): LLM errors should NOT cause default
rejection. Options:
  (a) Retry once before giving up
  (b) Return a neutral score (0.6) that lets rule_precheck decide
  (c) Mark as llm_error but don't force score below threshold
"""

import json

from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verifier.faithfulness_verifier import verify_tuples


# ── Fake LLM Clients that raise different exceptions ──────────────


class FakeLLMNetworkError:
    """Mock LLM client that raises ConnectionError on every chat() call."""

    model_name = "fake-network-error-model"
    base_url = "https://fake.test/v1"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        raise ConnectionError("Simulated network timeout")


class FakeLLMJSONParseError:
    """Mock LLM client that returns malformed JSON (not parseable)."""

    model_name = "fake-json-error-model"
    base_url = "https://fake.test/v1"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return type(
            "FakeResponse",
            (),
            {
                "content": "This is not valid JSON {broken",
                "response_id": f"fake-resp-{self.calls}",
            },
        )()


class FakeLLMRateLimitError:
    """Mock LLM client that raises RateLimitError (simulated)."""

    model_name = "fake-rate-limit-model"
    base_url = "https://fake.test/v1"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("HTTP 429: Rate limit exceeded")


class FakeLLMGenericError:
    """Mock LLM client that raises a generic Exception."""

    model_name = "fake-generic-error-model"
    base_url = "https://fake.test/v1"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        raise Exception("Simulated generic LLM error")


# ── Helper factories (same pattern as test_verifier_rejection_fix.py) ──


def make_prediction(**overrides) -> PredictionTuple:
    """Create a Chinese-language prediction tuple with sensible defaults."""
    defaults = {
        "event_id": "E001",
        "stakeholder": "白云区政府",
        "opinion": "白云区政府印发了城中村改造征收补偿安置方案并征求公众意见",
        "sentiment": "neutral",
        "rationale": "白云区政府印发补偿安置方案并组织征求意见",
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
    """Create a Chinese-language evidence record."""
    defaults = {
        "event_id": event_id,
        "evidence_id": evidence_id,
        "source": "official",
        "text": text,
    }
    defaults.update(overrides)
    return EvidenceRecord(**defaults)


# ══════════════════════════════════════════════════════════════════
# Test 1: Network timeout should not reject all tuples
# ══════════════════════════════════════════════════════════════════

def test_llm_network_timeout_does_not_reject_all():
    """When LLM client raises ConnectionError (network timeout), verify_tuples
    should NOT mark all tuples as insufficient_evidence.

    Current bug: _llm_verify() catches Exception and returns score=0.5.
    With config threshold=0.75 (used in paper.yaml/ablation.yaml), 0.5 < 0.75
    → tuple rejected. This is the ACTUAL production scenario.

    Expected: tuple should be accepted (or at least not rejected solely due
    to LLM error). Options:
      - LLM error → score=0.6 (neutral, lets rule_precheck decide)
      - LLM error → mark as llm_error but use rule_precheck result
      - LLM error → retry once

    This test uses threshold=0.75 (matching config) to reproduce the
    production bug. After fix (Task 8 + Task 9), the LLM error fallback
    should return a score ≥ 0.75 or the threshold should be lowered to 0.45.
    """
    fake_llm = FakeLLMNetworkError()

    predictions = [
        make_prediction(
            stakeholder="广州市白云区政府",
            opinion="白云区政府印发了城中村改造征收补偿安置方案",
            sentiment="neutral",
            rationale="白云区政府印发补偿安置方案",
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
        threshold=0.45,  # matches unified config threshold (Task 9 fix)
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert fake_llm.calls >= 1, "LLM should have been called at least once"
    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: score=0.5 (from error fallback), 0.5 < 0.75 → rejected
    # The tuple has valid evidence and rule_precheck passes, but LLM error
    # causes default rejection. This is the production bug.
    assert verified[0].verified is True, (
        f"BUG: LLM network timeout caused tuple to be rejected at config threshold 0.75. "
        f"support_score={verified[0].support_score}, "
        f"support_label={verified[0].support_label}, "
        f"verified={verified[0].verified}, "
        f"llm_details={verified[0].verification_diagnosis.get('llm_reason')}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 2: JSON parse failure should not reject all tuples
# ══════════════════════════════════════════════════════════════════

def test_llm_json_parse_failure_does_not_reject_all():
    """When LLM returns malformed JSON that cannot be parsed, verify_tuples
    should NOT mark all tuples as insufficient_evidence.

    Current bug: _llm_verify() tries json.loads(m.group()) but m is None
    when no JSON found → json.loads(None) raises → caught by except Exception
    → returns score=0.5 → below threshold → rejected.

    Expected: JSON parse failure should not cause default rejection. The
    tuple has valid evidence and rule_precheck passes.
    """
    fake_llm = FakeLLMJSONParseError()

    predictions = [
        make_prediction(
            stakeholder="三元里村村民",
            opinion="村民对城中村改造补偿方案存在不同意见",
            sentiment="mixed",
            rationale="部分村民支持改造但对补偿标准有异议",
            evidence_ids=["ev-002"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-002",
            text=(
                "三元里村村民对城中村改造补偿方案存在不同意见，"
                "部分居民支持改造但认为补偿标准偏低，希望提高补偿额度。"
            ),
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,  # matches unified config threshold (Task 9 fix)
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert fake_llm.calls >= 1, "LLM should have been called at least once"
    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: score=0.5 (from error fallback), 0.5 < 0.75 → verified=False
    assert verified[0].verified is True, (
        f"BUG: LLM JSON parse failure caused tuple to be rejected at config threshold 0.75. "
        f"support_score={verified[0].support_score}, "
        f"support_label={verified[0].support_label}, "
        f"verified={verified[0].verified}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 3: API rate limit should not reject all tuples
# ══════════════════════════════════════════════════════════════════

def test_llm_rate_limit_does_not_reject_all():
    """When LLM API returns rate limit error (HTTP 429), verify_tuples
    should NOT mark all tuples as insufficient_evidence.

    Current bug: RuntimeError from chat() is caught by except Exception
    → returns score=0.5 → below threshold → rejected.

    Expected: Rate limiting is a transient infrastructure issue, not a
    verdict on evidence quality. The tuple should not be rejected.
    """
    fake_llm = FakeLLMRateLimitError()

    predictions = [
        make_prediction(
            stakeholder="广州市教育局",
            opinion="教育局发布了校外培训机构管理办法",
            sentiment="neutral",
            rationale="教育局规范校外培训机构经营行为",
            evidence_ids=["ev-003"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-003",
            event_id="E001",
            text=(
                "广州市教育局正式发布《校外培训机构管理办法》，"
                "对培训机构的设立、经营和监管作出明确规定。"
            ),
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,  # matches unified config threshold (Task 9 fix)
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert fake_llm.calls >= 1, "LLM should have been called at least once"
    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: score=0.5 (from error fallback), 0.5 < 0.75 → verified=False
    assert verified[0].verified is True, (
        f"BUG: LLM rate limit error caused tuple to be rejected at config threshold 0.75. "
        f"support_score={verified[0].support_score}, "
        f"support_label={verified[0].support_label}, "
        f"verified={verified[0].verified}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 4: Generic LLM error should not reject all tuples
# ══════════════════════════════════════════════════════════════════

def test_llm_generic_error_does_not_reject_all():
    """When LLM client raises a generic Exception, verify_tuples should NOT
    mark all tuples as insufficient_evidence.

    Current bug: Any Exception → score=0.5 → below threshold → rejected.

    Expected: Generic errors should not cause default rejection.
    """
    fake_llm = FakeLLMGenericError()

    predictions = [
        make_prediction(
            stakeholder="医院管理层",
            opinion="医院发布了医患纠纷处置方案",
            sentiment="neutral",
            rationale="医院回应医患纠纷并公布处理措施",
            evidence_ids=["ev-004"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-004",
            event_id="E001",
            text=(
                "某医院管理层针对近期医患纠纷事件发布处置方案，"
                "成立专项工作组并公布处理措施。"
            ),
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,  # matches unified config threshold (Task 9 fix)
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert fake_llm.calls >= 1, "LLM should have been called at least once"
    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: score=0.5 (from error fallback), 0.5 < 0.75 → verified=False
    assert verified[0].verified is True, (
        f"BUG: Generic LLM error caused tuple to be rejected at config threshold 0.75. "
        f"support_score={verified[0].support_score}, "
        f"support_label={verified[0].support_label}, "
        f"verified={verified[0].verified}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 5: LLM error fallback score should be neutral, not 0.5
# ══════════════════════════════════════════════════════════════════

def test_llm_error_fallback_score_is_neutral_not_0_5():
    """The LLM error fallback score should be neutral (≥0.6) or marked
    specially, NOT 0.5 which is ambiguous.

    Current bug: _llm_verify() returns score=0.5 on error. This is:
      - Below config threshold 0.75 → rejected
      - Below code default threshold 0.45 → barely accepted (but still ambiguous)
      - Not clearly marked as an error case

    Expected: Error fallback should return a score that:
      - Is ≥ 0.6 (neutral, lets rule_precheck decide)
      - OR is marked with a special flag (llm_error=True)
      - So that the tuple is not rejected solely due to infrastructure issues
    """
    fake_llm = FakeLLMNetworkError()

    predictions = [
        make_prediction(
            stakeholder="白云区政府",
            opinion="白云区政府印发补偿安置方案",
            sentiment="neutral",
            rationale="白云区政府印发补偿安置方案",
            evidence_ids=["ev-005"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-005",
            text="白云区政府印发了城中村改造征收补偿安置方案。",
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,  # matches unified config threshold (Task 9 fix)
        llm_client=fake_llm,
        mode="decomposed",
    )

    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: score=0.6 (after Task 8 fix), 0.6 >= 0.45 threshold → verified=True
    # Expected: LLM error should NOT cause rejection. Either:
    #   (a) score ≥ 0.45 (error doesn't affect verification), OR
    #   (b) error is retried and successful, OR
    #   (c) rule_precheck result is used instead of LLM error fallback
    assert verified[0].support_score >= 0.45 or verified[0].verified is True, (
        f"BUG: LLM error fallback score={verified[0].support_score} is below "
        f"unified threshold 0.45, causing rejection. "
        f"support_label={verified[0].support_label}, verified={verified[0].verified}. "
        f"LLM errors should not cause default rejection."
    )
