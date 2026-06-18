"""Integration tests for verifier full verify_tuples() call chain.

Tests the complete verify_tuples() pipeline including rule_precheck,
_llm_verify, _relax_precheck_flags, _merge_issue_flags,
_apply_hard_flag_score_cap, and decomposed_diagnosis — all with mock LLM.

Uses real Chinese event/evidence fixtures and the FakeLLMClient pattern
established in test_verifier_rejection_fix.py.
"""

import json

import pytest

from episoa.data.schema import EvidenceRecord, PredictionTuple
from episoa.verifier.faithfulness_verifier import verify_tuples


# ── Mock LLM Client ──────────────────────────────────────────────────


class FakeLLMClient:
    """Mock LLM client that returns canned JSON responses for testing.

    Supports single-score mode (score + content_override) and
    multi-score mode (scores list consumed sequentially).
    """

    model_name = "fake-test-model"
    base_url = "https://fake.test/v1"

    def __init__(
        self,
        score: float = 0.5,
        content_override: dict | None = None,
        scores: list[float] | None = None,
    ):
        self.score = score
        self.content_override = content_override or {}
        self.scores = scores
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        if self.scores is not None:
            current_score = self.scores[min(self.calls - 1, len(self.scores) - 1)]
        else:
            current_score = self.score
        payload: dict = {
            "score": current_score,
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
            {"content": json.dumps(payload, ensure_ascii=False)},
        )()


# ── Helper Factories ─────────────────────────────────────────────────


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


# ══════════════════════════════════════════════════════════════════════
# REAL EVIDENCE FIXTURES (trimmed from evidence_v3_repaired_plus_low37.jsonl)
# ══════════════════════════════════════════════════════════════════════

EVIDENCE_E001_SANYUANLI = (
    "属于白云新城辐射带的三元里村，改造已是大势所趋。截至5月30日，三元里城中村的"
    "居民同意城中村改造比率超过了80%，拆迁补偿方案支持比率为33.62%。城中村改造，"
    "集体和居民最直接的得益是什么？改造后，这里的区域优势将会凸显，我们可以将集体"
    "物业由过去的简单租赁提升到以商贸、文化、饮食、旅业、服务为主体的产业，从中"
    "获得更大的收益。三元里村党委书记韦联建如是说。"
    "成立公司防止烂尾。改造过程中，上级下拨的资金将如何运作？会否出现改造烂尾的"
    "现象？为此，三元里村成立了三元里建设投资有限公司，服务于整个城中村改造的过程。"
)

EVIDENCE_E006_MEIXIN = (
    "两个星期过去，围绕着小区物业费涨价的争论在广州市番禺区大龙街道美心翡翠明庭"
    "小区还是日益激烈，大家都在追问：公示的投票结果与实际调查为什么相差那么大？"
    "是谁在作假？翡翠明庭已是一个10多年的小区。对服务不满却同意涨价？"
    "17日中午，记者来到该小区，注意到虽然刚搞了卫生，但仍掩不住这个2004年就建成的"
    "有近千户业主的小区老旧之态。业主李小姐告诉记者，她居住在此已10多年了，感觉"
    "物业服务态度恶劣，对业主诉求置若罔闻，大家都一直在忍，却因物业费要涨价而爆发了。"
    "负责小区物业的广州市创佳物业管理有限公司，是番禺本地颇具规模的物业公司，管理着"
    "多个小区。2024年9月13日，美心翡翠明庭小区物业管理委员会骤然提出一系列重要议题，"
    "其中最为引人关注的便是物业费涨价方案。"
)

EVIDENCE_E032_SAFETY = (
    "国务院安委办、应急管理部：五一假期，生产经营单位要深入排查风险隐患，强化重大"
    "危险源管理，加强值班值守，完善应急处置预案，防范事故发生。"
    "国务院安委办、应急管理部：五一假期，交通运输、旅游景点、人员密集场所安全风险"
    "较高，注意加强安全防范。"
)

EVIDENCE_BAIYUN_DISTRICT = (
    "日前，广州市白云区人民政府正式印发了三元里村城中村改造项目土地及房屋征收补偿"
    "安置方案，拟征地面积375301平方米。该方案明确了征收范围、补偿标准和安置方式，"
    "并同步开展公众意见征集工作。"
)


# ══════════════════════════════════════════════════════════════════════
# Test 1: Empty predictions returns empty list
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_empty_predictions_returns_empty():
    """verify_tuples([], evidence) should return an empty list immediately
    without calling any LLM or performing prechecks."""
    evidence_list = [
        make_evidence(
            evidence_id="ev-001",
            text=EVIDENCE_BAIYUN_DISTRICT,
        )
    ]
    fake_llm = FakeLLMClient(score=0.85)

    verified = verify_tuples([], evidence_list, llm_client=fake_llm, mode="decomposed")

    assert isinstance(verified, list), "Should return a list"
    assert len(verified) == 0, "Empty predictions should yield empty output"
    assert fake_llm.calls == 0, "LLM should NOT be called for empty input"


# ══════════════════════════════════════════════════════════════════════
# Test 2: All predictions verified with mock LLM (positive path)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_all_predictions_verified_with_mock_llm():
    """When mock LLM returns high scores and all evidence IDs exist,
    all predictions should be verified=True."""
    fake_llm = FakeLLMClient(score=0.85)

    predictions = [
        make_prediction(
            event_id="E001",
            stakeholder="三元里村党委及村集体",
            opinion="明确支持旧改项目，认为改造将推动产业升级并提升集体收益",
            sentiment="positive",
            rationale="村党委书记公开表态支持改造并阐述经济收益",
            evidence_ids=["ev-00023"],
            event_chain_stage="response",
        ),
        make_prediction(
            event_id="E006",
            stakeholder="广州市创佳物业管理有限公司",
            opinion="发起并推进小区物业费上调表决程序",
            sentiment="neutral",
            rationale="该公司为小区实际物业管理方并主导了涨价表决",
            evidence_ids=["ev-00116"],
            event_chain_stage="trigger",
        ),
        make_prediction(
            event_id="E032",
            stakeholder="国务院安委办",
            opinion="针对五一假期发布安全提示，要求排查风险隐患",
            sentiment="neutral",
            rationale="证据记载国务院安委办联合应急管理部发布假期安全防范要求",
            evidence_ids=["ev-00764"],
            event_chain_stage="response",
        ),
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-00023",
            event_id="E001",
            text=EVIDENCE_E001_SANYUANLI,
        ),
        make_evidence(
            evidence_id="ev-00116",
            event_id="E006",
            text=EVIDENCE_E006_MEIXIN,
        ),
        make_evidence(
            evidence_id="ev-00764",
            event_id="E032",
            text=EVIDENCE_E032_SAFETY,
            source="official",
        ),
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 3, "Should return 3 verified tuples"
    assert fake_llm.calls == 3, "LLM should have been called for all 3 predictions"

    for i, vt in enumerate(verified):
        assert vt.verified is True, (
            f"Prediction {i} should be verified (score={vt.support_score}, "
            f"label={vt.support_label}, flags={vt.verification_diagnosis.get('issue_flags')})"
        )
        assert vt.support_score >= 0.45, (
            f"Prediction {i} support_score={vt.support_score} should be >= default threshold 0.45"
        )
        assert vt.support_label == "supported", (
            f"Prediction {i} support_label={vt.support_label} should be 'supported'"
        )
        assert "verification_diagnosis" in vt.model_dump(), (
            f"Prediction {i} should have verification_diagnosis"
        )


# ══════════════════════════════════════════════════════════════════════
# Test 3: Mixed verification — some pass, some fail
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_mixed_verification_mock_llm():
    """Test mixed outcomes: good evidence passes, missing evidence fails,
    and LLM-returned low score also fails."""
    # pred1: high LLM score → verified
    # pred2: low LLM score → not verified
    # pred3: missing evidence → score=0.0 → not verified (no LLM call)
    fake_llm = FakeLLMClient(scores=[0.85, 0.30])

    predictions = [
        make_prediction(
            event_id="E001",
            stakeholder="三元里村党委",
            opinion="明确支持旧改项目",
            sentiment="positive",
            rationale="村党委书记公开表态支持改造",
            evidence_ids=["ev-00023"],
        ),
        make_prediction(
            event_id="E006",
            stakeholder="广州市创佳物业管理有限公司",
            opinion="发起物业费涨价表决",
            sentiment="neutral",
            rationale="主导了涨价表决程序",
            evidence_ids=["ev-00116"],
        ),
        make_prediction(
            event_id="E999",
            stakeholder="不存在的利益相关方",
            opinion="不存在的主张",
            sentiment="neutral",
            rationale="不存在的理由",
            evidence_ids=["ev-missing-999"],  # no matching evidence
        ),
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-00023",
            event_id="E001",
            text=EVIDENCE_E001_SANYUANLI,
        ),
        make_evidence(
            evidence_id="ev-00116",
            event_id="E006",
            text=EVIDENCE_E006_MEIXIN,
        ),
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 3, "Should return 3 tuples"
    # pred1: good evidence + high score → verified
    assert verified[0].verified is True, (
        f"Prediction 0 (high score) should be verified, "
        f"got score={verified[0].support_score}"
    )
    # pred2: evidence exists but LLM score=0.30 < 0.45 → not verified
    assert verified[1].verified is False, (
        f"Prediction 1 (low LLM score) should NOT be verified, "
        f"got score={verified[1].support_score}"
    )
    # pred3: missing evidence → score=0.0 → not verified; no LLM call
    assert verified[2].verified is False, (
        f"Prediction 2 (missing evidence) should NOT be verified"
    )
    assert verified[2].support_score == 0.0, (
        f"Prediction 2 score should be 0.0 for missing evidence, "
        f"got {verified[2].support_score}"
    )
    assert "missing_evidence" in verified[2].verification_diagnosis.get("issue_flags", []), (
        "Prediction 2 should have 'missing_evidence' issue flag"
    )

    # LLM called only for the first 2 (not pred3 with missing evidence)
    assert fake_llm.calls == 2, (
        f"LLM should be called only for predictions with evidence, "
        f"got {fake_llm.calls} calls"
    )


# ══════════════════════════════════════════════════════════════════════
# Test 4: Quality gate filters low scores at elevated threshold
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_quality_gate_filters_low_score():
    """With threshold=0.80 (high gate), even a reasonable mock LLM score
    of 0.50 should result in verified=False for all predictions."""
    fake_llm = FakeLLMClient(score=0.50)

    predictions = [
        make_prediction(
            event_id="E001",
            stakeholder="三元里村村民",
            opinion="村民同意城中村改造方案",
            sentiment="positive",
            rationale="村民质疑补偿方案但最终同意改造",
            evidence_ids=["ev-00023"],
        ),
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-00023",
            event_id="E001",
            text=EVIDENCE_E001_SANYUANLI,
        ),
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.80,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 1
    assert fake_llm.calls == 1, "LLM should be called"
    assert verified[0].verified is False, (
        f"Score 0.50 < threshold 0.80 should be rejected, "
        f"got verified={verified[0].verified}, score={verified[0].support_score}"
    )
    assert verified[0].support_score == 0.50
    # support_label should not be "supported" since score < threshold
    assert verified[0].support_label != "supported", (
        f"support_label should not be 'supported' when below threshold, "
        f"got {verified[0].support_label}"
    )


# ══════════════════════════════════════════════════════════════════════
# Test 5: Threshold sweep — verify behavior at 0.3, 0.5, 0.7
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_threshold_sweep():
    """Test the same predictions+evidence across three thresholds to verify
    that verified=True/False boundary works correctly."""
    predictions = [
        make_prediction(
            event_id="E001",
            stakeholder="三元里村党委",
            opinion="支持旧改项目并推动产业升级",
            sentiment="positive",
            rationale="村党委书记表示改造将带来更大收益",
            evidence_ids=["ev-00023"],
        ),
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-00023",
            event_id="E001",
            text=EVIDENCE_E001_SANYUANLI,
        ),
    ]

    thresholds = [0.3, 0.5, 0.7]
    expected = [True, True, False]  # with mock score=0.55

    for threshold, expect_verified in zip(thresholds, expected):
        fake_llm = FakeLLMClient(score=0.55)

        verified = verify_tuples(
            predictions,
            evidence_list,
            threshold=threshold,
            llm_client=fake_llm,
            mode="decomposed",
        )

        assert len(verified) == 1
        assert fake_llm.calls == 1, f"LLM should be called for threshold={threshold}"

        vt = verified[0]
        if expect_verified:
            assert vt.verified is True, (
                f"At threshold={threshold}, score=0.55 should be verified=True, "
                f"got verified={vt.verified}, support_label={vt.support_label}"
            )
        else:
            assert vt.verified is False, (
                f"At threshold={threshold}, score=0.55 should be verified=False, "
                f"got verified={vt.verified}, support_label={vt.support_label}"
            )

        assert vt.support_score == 0.55, (
            f"Score should be 0.55 at all thresholds, got {vt.support_score}"
        )


# ══════════════════════════════════════════════════════════════════════
# Test 6: Chinese entity name variation accepted
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_chinese_entity_name_variation_accepted():
    """Evidence mentions 广州市白云区政府, tuple stakeholder is 广州市政府.
    The verifier prompt explicitly allows approximate name matching,
    and the mock LLM returns a positive score. The tuple should be accepted."""
    fake_llm = FakeLLMClient(score=0.70)

    predictions = [
        make_prediction(
            event_id="E001",
            stakeholder="广州市政府",
            opinion="印发三元里村城中村改造征收补偿安置方案并征求公众意见",
            sentiment="neutral",
            rationale="广州市政府发布补偿安置方案",
            evidence_ids=["ev-baiyun-001"],
        ),
    ]
    evidence_list = [
        make_evidence(
            evidence_id="ev-baiyun-001",
            event_id="E001",
            text=EVIDENCE_BAIYUN_DISTRICT,
        ),
    ]

    verified = verify_tuples(
        predictions,
        evidence_list,
        threshold=0.45,
        llm_client=fake_llm,
        mode="decomposed",
    )

    assert len(verified) == 1
    assert fake_llm.calls == 1, "LLM should be called for name variation check"

    vt = verified[0]
    assert vt.verified is True, (
        f"Chinese entity name variation (广州市白云区政府 → 广州市政府) "
        f"should be accepted. Got verified={vt.verified}, "
        f"score={vt.support_score}, label={vt.support_label}, "
        f"flags={vt.verification_diagnosis.get('issue_flags')}"
    )
    assert vt.support_label == "supported", (
        f"Should be 'supported' with score 0.70, got {vt.support_label}"
    )
    # Verify diagnosis was produced
    diagnosis = vt.verification_diagnosis
    assert isinstance(diagnosis, dict), "verification_diagnosis should be a dict"
    assert "support_score" in diagnosis, "diagnosis should include support_score"
    assert "issue_flags" in diagnosis, "diagnosis should include issue_flags"
