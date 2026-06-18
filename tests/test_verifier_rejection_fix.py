"""TDD RED-phase tests for verifier over-rejection bugs.

Task 4 of EpiSOA remediation Wave 1: capture over-rejection bugs as failing tests.
These tests MUST FAIL with current code (RED phase). They will be used in
Wave 2 Tasks 8-9 to verify fixes (GREEN phase).

Over-rejection patterns tested:
  - evidence_span_not_supported false positives (paraphrased spans)
  - stage_mismatch false positives (evidence-supported stage not in known_stages)
  - LLM verifier score threshold too strict (score=0.5 rejected at 0.75)
  - rationale_not_supported false positives (minor wording differences)
  - contradiction_detected false positives (single negative term in supportive evidence)
"""

import json

from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verifier.faithfulness_verifier import verify_tuples


class FakeLLMClient:
    """Mock LLM client that returns canned JSON responses for testing."""

    model_name = "fake-test-model"
    base_url = "https://fake.test/v1"

    def __init__(self, score: float = 0.5, content_override: dict | None = None):
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
                "opinion_support": "partial",
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


# ── Helper factories ─────────────────────────────────────────────


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
# Test 1: evidence_span_not_supported false positive
# ══════════════════════════════════════════════════════════════════

def test_evidence_span_paraphrase_triggers_false_positive():
    """Rule precheck wrongly flags evidence_span_not_supported when spans are
    semantically accurate paraphrases rather than exact substrings.

    Current bug: evidence_spans_supported_by_evidence() requires each span's
    text to literally appear in the combined evidence text. Paraphrased spans
    trigger evidence_span_not_supported (a HARD flag), capping score at 0.39,
    which is < 0.75 threshold → always rejected.
    """
    predictions = [
        make_prediction(
            stakeholder="广州市白云区政府",
            opinion="白云区政府印发了城中村改造征收补偿安置方案，并征求公众意见",
            sentiment="neutral",
            rationale="白云区政府印发补偿安置方案并征求公众意见",
            evidence_ids=["ev-001"],
            evidence_spans=[
                {
                    "evidence_id": "ev-001",
                    "text": "白云区政府印发三元里村城中村改造征收补偿安置方案并征求公众意见",
                }
            ],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text=(
                "日前，广州市白云区人民政府正式印发了三元里村城中村改造项目"
                "土地及房屋征收补偿安置方案，拟征地面积375301平方米。"
                "该方案明确了征收范围、补偿标准和安置方式，"
                "并同步开展公众意见征集工作。"
            ),
        )
    ]

    verified = verify_tuples(predictions, evidence_list, mode="decomposed")

    # The span text "白云区政府印发三元里村城中村改造征收补偿安置方案并征求公众意见"
    # is a paraphrase — it does NOT appear literally in evidence because:
    #   - Evidence says "广州市白云区人民政府" not "白云区政府"
    #   - Evidence says "正式印发了" not just "印发"
    #   - Evidence says "公众意见征集" not "征求公众意见"
    # So evidence_spans_supported_by_evidence() returns False → hard flag.
    # But the span is semantically accurate → this is a FALSE rejection.
    #
    # ─────────── RED PHASE: this assertion FAILS ───────────
    assert verified[0].verified is True, (
        f"BUG: evidence_span_not_supported false positive. "
        f"Span text is a semantically correct paraphrase of the evidence. "
        f"support_score={verified[0].support_score}, "
        f"issue_flags={verified[0].verification_diagnosis.get('issue_flags')}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 2: stage_mismatch false positive
# ══════════════════════════════════════════════════════════════════

def test_stage_mismatch_when_evidence_clearly_supports_stage():
    """Rule precheck wrongly flags stage_mismatch when the prediction's stage
    is clearly supported by evidence content, but not listed in
    chain_stages_by_event.

    Current bug: rule_precheck purely checks if event_chain_stage is in
    known_stages, without consulting evidence content. If chain_stages_by_event
    is incomplete (e.g., missing "resolution"), legitimate tuples are rejected.
    """
    predictions = [
        make_prediction(
            event_id="E002",
            stakeholder="江西省联合调查组",
            opinion="联合调查组发布鼠头鸭脖事件调查结果并追究相关责任人",
            sentiment="neutral",
            rationale="江西省联合调查组认定异物为鼠头并追究责任",
            evidence_ids=["ev-002"],
            event_chain_stage="resolution",
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-002",
            event_id="E002",
            text=(
                "江西省联合调查组发布通报，确认江西工业职业技术学院食堂"
                "饭菜中的异物为鼠头，并对相关责任人进行处理。"
            ),
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        mode="decomposed",
        # "resolution" is a legitimate stage but missing from known_stages
        chain_stages_by_event={"E002": {"trigger", "diffusion", "response"}},
    )

    # Evidence clearly describes a resolution action (investigation result
    # publication + accountability measures). But chain_stages_by_event
    # doesn't include "resolution", so rule_precheck flags stage_mismatch
    # → hard flag → score capped at 0.39 → rejected.
    #
    # ─────────── RED PHASE: this assertion FAILS ───────────
    assert verified[0].verified is True, (
        f"BUG: stage_mismatch false positive. "
        f"Evidence clearly supports 'resolution' stage but chain_stages_by_event "
        f"is incomplete. support_score={verified[0].support_score}, "
        f"issue_flags={verified[0].verification_diagnosis.get('issue_flags')}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 3: LLM verifier score threshold too strict
# ══════════════════════════════════════════════════════════════════

def test_llm_score_0_5_rejected_at_default_threshold():
    """LLM gives score=0.5 (partially supported) to a valid tuple, but the
    default threshold=0.75 rejects it unconditionally.

    Current bug: threshold=0.75 is too high. A score of 0.5 means the LLM
    finds meaningful partial support — the tuple should be accepted under a
    reasonable threshold (e.g., ≥0.5), not rejected as "insufficient_evidence".
    """
    fake_llm = FakeLLMClient(score=0.5)

    predictions = [
        make_prediction(
            stakeholder="三元里村村民",
            opinion="村民对改造补偿方案支持度一般，但对整体改造持积极态度",
            sentiment="mixed",
            rationale="调查显示补偿方案支持率仅33%，但改造同意率超过80%",
            evidence_ids=["ev-003"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-003",
            text=(
                "截至5月30日，三元里村村民同意城中村改造比率超过了80%，"
                "拆迁补偿方案支持比率为33.62%。"
                "大部分居民支持改造，但对补偿方案有不同意见。"
            ),
        )
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert fake_llm.calls == 1, "LLM should have been called exactly once"
    # With default threshold=0.75: score=0.5 → 0.5 < 0.75 → rejected.
    # But this tuple has real partial evidence support and the LLM
    # correctly identifies it as such. Score=0.5 should be acceptable.
    #
    # ─────────── RED PHASE: this assertion FAILS ───────────
    assert verified[0].verified is True, (
        f"BUG: LLM score=0.5 rejected at default threshold=0.75. "
        f"support_score={verified[0].support_score}, "
        f"support_label={verified[0].support_label}, "
        f"issue_flags={verified[0].verification_diagnosis.get('issue_flags')}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 4: rationale_not_supported false positive (wording diff)
# ══════════════════════════════════════════════════════════════════

def test_rationale_check_too_strict_minor_wording_difference():
    """Rule precheck wrongly flags rationale_not_supported when the rationale
    uses slightly different wording from the evidence but conveys the same
    semantic meaning.

    Current bug: claim_supported_by_evidence() requires ≥2 meaningful token
    matches. With divergent phrasings for the same concept (e.g., "具体数额"
    vs "标准", "安置房源" vs "回迁安排"), the overlap falls below the
    threshold → rationale_not_supported → hard flag → rejected.
    """
    predictions = [
        make_prediction(
            stakeholder="白云区政府",
            opinion="白云区政府明确了征收补偿标准和安置方案",
            sentiment="neutral",
            rationale="方案明确了补偿具体数额和安置房源",
            evidence_ids=["ev-004"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-004",
            text="白云区政府发布了关于补偿标准及回迁安排的相关文件",
        )
    ]

    verified = verify_tuples(predictions, evidence_list, mode="decomposed")

    # Rationale "方案明确了补偿具体数额和安置房源" and evidence
    # "关于补偿标准及回迁安排的相关文件" convey the same idea
    # (compensation details + relocation), but only "补偿" matches
    # as a 2-char token ("数额/安置/房源" vs "标准/回迁" don't overlap).
    # One matching token < 2 required → rationale_not_supported.
    # This is a false positive because the semantic content is equivalent.
    #
    # ─────────── RED PHASE: this assertion FAILS ───────────
    assert verified[0].verified is True, (
        f"BUG: rationale_not_supported false positive. "
        f"Rationale and evidence convey same meaning with different wording. "
        f"support_score={verified[0].support_score}, "
        f"issue_flags={verified[0].verification_diagnosis.get('issue_flags')}"
    )


# ══════════════════════════════════════════════════════════════════
# Test 5: contradiction_detected false positive
# ══════════════════════════════════════════════════════════════════

def test_contradiction_single_negative_term_in_supportive_evidence():
    """Rule precheck wrongly flags contradiction_detected when evidence
    contains one negative attitude term but overall supports the positive claim.

    Current bug: _obvious_contradiction() checks NEGATIVE_ATTITUDE_TERMS
    against the full evidence text. A single word like "质疑" or "不满"
    in a nuanced passage triggers contradiction even when the surrounding
    context and conclusion clearly support the positive sentiment.

    POSITIVE_ATTITUDE_TERMS = ["支持","点赞","满意","认可","感谢","欢迎","肯定","赞扬","好事","益处","有益"]
    NEGATIVE_ATTITUDE_TERMS = ["反对","质疑","投诉","举报","抵触","不同意","难以接受","担忧"]

    The word "同意" (agree/consent) is NOT in POSITIVE_ATTITUDE_TERMS, so
    evidence containing only negative terms + "同意" gets evidence_positive=False.
    """
    predictions = [
        make_prediction(
            stakeholder="三元里村村民",
            opinion="村民同意城中村改造方案",
            sentiment="positive",
            rationale="村民质疑补偿方案但最终同意改造",
            evidence_ids=["ev-005"],
        )
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-005",
            text=(
                "三元里村部分村民质疑补偿方案的合理性并表示不满，"
                "但经过协调沟通，最终大部分村民同意并签署了改造方案。"
            ),
        )
    ]

    verified = verify_tuples(predictions, evidence_list, mode="decomposed")

    # Evidence contains "质疑" and "不满" → evidence_negative=True
    # "同意" is NOT in POSITIVE_ATTITUDE_TERMS list → evidence_positive=False
    # sentiment="positive" → positive_claim=True
    # Rule: positive_claim & evidence_negative & !evidence_positive → contradiction
    # → contradiction_detected → hard flag → score capped at 0.39 → rejected
    #
    # BUT: the evidence clearly supports the claim — "最终大部分村民同意并签署了
    # 改造方案" is the outcome. The earlier "质疑" is contextual, not contradictory.
    # This is a FALSE rejection.
    #
    # ─────────── RED PHASE: this assertion FAILS ───────────
    assert verified[0].verified is True, (
        f"BUG: contradiction_detected false positive. "
        f"Evidence supports the positive claim ('同意并签署') despite containing "
        f"negative terms in a nuanced passage. "
        f"support_score={verified[0].support_score}, "
        f"issue_flags={verified[0].verification_diagnosis.get('issue_flags')}"
    )
