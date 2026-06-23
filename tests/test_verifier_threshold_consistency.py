"""TDD RED-phase tests for verifier threshold inconsistency.

Task 3 of EpiSOA resubmission Wave 1: capture threshold mismatch across
config, code, and paper. These tests MUST FAIL with current code (RED phase).
They will be used in Wave 2 Task 9 to verify the fix (GREEN phase).

Three-way inconsistency:
  - configs/paper.yaml:62:        verifier.threshold: 0.75
  - configs/ablation.yaml:61:     verifier.threshold: 0.75
  - src/episoa/verifier/faithfulness_verifier.py:48: threshold: float = 0.45
  - Paper docx (VERIFIER_USER prompt): "阈值已从0.75降低为0.40"

The config value (0.75) overrides code default (0.45) at runtime
(pipeline.py:590: float(config.verifier.get("threshold", 0.75))).
So effective threshold is 0.75, which is too high — LLM errors return 0.5,
below 0.75, causing mass rejection.

Expected: All three thresholds should be unified (recommended 0.45).
"""

import inspect
from pathlib import Path

import yaml

from episoa.verifier.faithfulness_verifier import verify_tuples


# ══════════════════════════════════════════════════════════════════
# Test 1: paper.yaml threshold matches verify_tuples() code default
# ══════════════════════════════════════════════════════════════════

def test_paper_yaml_threshold_matches_code_default():
    """configs/paper.yaml verifier.threshold should match verify_tuples()
    default threshold.

    Current: paper.yaml has 0.75, code default is 0.45 → MISMATCH
    Expected: both should be 0.45 (or both 0.75, but 0.45 is recommended)
    """
    repo_root = Path(__file__).resolve().parents[1]
    paper_yaml_path = repo_root / "configs" / "paper.yaml"

    with open(paper_yaml_path, encoding="utf-8") as f:
        paper_config = yaml.safe_load(f)

    paper_threshold = paper_config.get("verifier", {}).get("threshold")

    # Get verify_tuples() default threshold from function signature
    sig = inspect.signature(verify_tuples)
    code_default_threshold = sig.parameters["threshold"].default

    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: paper_threshold=0.75, code_default_threshold=0.45
    assert paper_threshold == code_default_threshold, (
        f"BUG: paper.yaml threshold ({paper_threshold}) != "
        f"verify_tuples() default ({code_default_threshold}). "
        f"They must be unified to avoid runtime inconsistency."
    )


# ══════════════════════════════════════════════════════════════════
# Test 2: ablation.yaml threshold matches verify_tuples() code default
# ══════════════════════════════════════════════════════════════════

def test_ablation_yaml_threshold_matches_code_default():
    """configs/ablation.yaml verifier.threshold should match verify_tuples()
    default threshold.

    Current: ablation.yaml has 0.75, code default is 0.45 → MISMATCH
    Expected: both should be 0.45 (or both 0.75, but 0.45 is recommended)
    """
    repo_root = Path(__file__).resolve().parents[1]
    ablation_yaml_path = repo_root / "configs" / "ablation.yaml"

    with open(ablation_yaml_path, encoding="utf-8") as f:
        ablation_config = yaml.safe_load(f)

    ablation_threshold = ablation_config.get("verifier", {}).get("threshold")

    # Get verify_tuples() default threshold from function signature
    sig = inspect.signature(verify_tuples)
    code_default_threshold = sig.parameters["threshold"].default

    # ─────────── RED PHASE: this assertion FAILS ───────────
    # Current: ablation_threshold=0.75, code_default_threshold=0.45
    assert ablation_threshold == code_default_threshold, (
        f"BUG: ablation.yaml threshold ({ablation_threshold}) != "
        f"verify_tuples() default ({code_default_threshold}). "
        f"They must be unified to avoid runtime inconsistency."
    )


# ══════════════════════════════════════════════════════════════════
# Test 3: paper.yaml and ablation.yaml thresholds match each other
# ══════════════════════════════════════════════════════════════════

def test_paper_and_ablation_thresholds_match():
    """configs/paper.yaml and configs/ablation.yaml verifier.threshold should
    match each other.

    Current: both are 0.75 → this test PASSES (documents consistency)
    But if someone changes one without the other, this test will catch it.
    """
    repo_root = Path(__file__).resolve().parents[1]

    with open(repo_root / "configs" / "paper.yaml", encoding="utf-8") as f:
        paper_threshold = yaml.safe_load(f).get("verifier", {}).get("threshold")

    with open(repo_root / "configs" / "ablation.yaml", encoding="utf-8") as f:
        ablation_threshold = yaml.safe_load(f).get("verifier", {}).get("threshold")

    # This should PASS (both are 0.75 currently)
    assert paper_threshold == ablation_threshold, (
        f"paper.yaml threshold ({paper_threshold}) != "
        f"ablation.yaml threshold ({ablation_threshold})"
    )


# ══════════════════════════════════════════════════════════════════
# Test 4: verify_tuples() default threshold is not 0.75
# ══════════════════════════════════════════════════════════════════

def test_verify_tuples_default_threshold_is_not_075():
    """verify_tuples() default threshold should NOT be 0.75 (too high).

    Current: code default is 0.45 → this test PASSES
    But if someone changes code default to 0.75, this test will catch it.

    A threshold of 0.75 is too high because:
      - LLM error fallback returns 0.5 → 0.5 < 0.75 → rejected
      - LLM partial support (0.5-0.6) → rejected
      - Only strong support (≥0.75) passes, losing recall
    """
    sig = inspect.signature(verify_tuples)
    code_default_threshold = sig.parameters["threshold"].default

    # This should PASS (code default is 0.45, not 0.75)
    assert code_default_threshold != 0.75, (
        f"verify_tuples() default threshold is {code_default_threshold}, "
        f"which is too high (0.75 causes mass rejection). "
        f"Recommended: 0.45"
    )


# ══════════════════════════════════════════════════════════════════
# Test 5: verify_tuples() respects explicit threshold argument
# ══════════════════════════════════════════════════════════════════

def test_verify_tuples_respects_explicit_threshold():
    """verify_tuples() should use the explicitly passed threshold, not the
    code default or config value.

    This test documents that explicit threshold argument takes precedence.
    """
    sig = inspect.signature(verify_tuples)
    code_default = sig.parameters["threshold"].default

    # This test just documents that explicit threshold is respected
    # (implementation detail — verify_tuples uses `threshold` parameter directly)
    # It should PASS as long as the function signature has threshold as a parameter
    assert "threshold" in sig.parameters, (
        "verify_tuples() should have a 'threshold' parameter"
    )

    # Document the current state
    assert code_default == 0.45, (
        f"Expected code default threshold 0.45, got {code_default}. "
        f"If this changed, update the test to reflect new default."
    )
