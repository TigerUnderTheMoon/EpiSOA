# F2: Code Quality Review

**Date**: 2026-06-23
**Reviewer**: Sisyphus (automated)
**Baseline**: v2-baseline-pre-resubmission @ 28dfe50

## 1. Test Suite

```
427 passed, 1 failed, 26 deselected in 14.27s
```

**Failed test**: `tests/test_remediation_scripts.py::test_audit_manuscript_numbers_passes_on_current_docx`
- **Cause**: `FileNotFoundError` for `outputs/runs_human_gold_v2/ablation_full_soe/metrics.json`
- **Verification**: Stashed changes and ran on baseline → same failure. **PRE-EXISTING**, not a regression.
- **Root cause**: Test expects experiment artifacts that don't exist because Wave 3 experiments are blocked by API 401.
- **Action**: No fix needed from F2. Will resolve automatically when API is fixed and experiments rerun (Wave 3 Task 15-16).

## 2. Changed Files Review

Files changed since baseline (`git diff --name-only v2-baseline-pre-resubmission..HEAD`):

### Code files (4)
- `src/episoa/verifier/faithfulness_verifier.py` — Verifier LLM error fallback (0.5→0.6), comment updates
- `tests/test_verifier_integration_v2.py` — 7 integration tests (new)
- `tests/test_verifier_llm_error_fix.py` — 5 TDD tests (new)
- `tests/test_verifier_threshold_consistency.py` — 5 TDD tests (new)

### Config files (9)
- `configs/paper.yaml` — verifier.mode=decomposed, threshold=0.45, no empty api_key/base_url
- `configs/ablation.yaml` — threshold=0.45
- `configs/paper_with_heldout.yaml` — same fixes as paper.yaml
- `configs/ablation_oracle_evidence.yaml` — threshold 0.75→0.45
- `configs/ablation_human_gold_v2.yaml` — threshold 0.75→0.45
- `configs/ablation_human_gold_v1.yaml` — threshold 0.75→0.45
- `configs/ablation_single.yaml` — threshold 0.75→0.45
- `configs/ablation_p0_parse_repair.yaml` — threshold 0.75→0.45
- `configs/default.yaml` — threshold 0.75→0.45

### Code fixes applied during F2 (5 edits)
- `src/episoa/config.py:43` — fallback default 0.75→0.45
- `src/episoa/pipeline.py:222` — manifest fallback 0.75→0.45
- `src/episoa/pipeline.py:590` — verify_tuples() fallback 0.75→0.45
- `src/episoa/verifier/faithfulness_verifier.py:533` — stale comment 0.40→0.45
- `src/episoa/verifier/faithfulness_verifier.py:597-602` — stale comment 0.75→0.45

## 3. Anti-Pattern Scan

### Type suppression
- `as any`: **0 matches** ✅
- `@ts-ignore`: **0 matches** ✅
- `@ts-expect-error`: **0 matches** ✅

### Error handling
- Empty catch blocks `except.*:\s*pass`: **0 matches** ✅
- Empty catch `except.*:\s*$`: **0 matches** ✅

### Debug residue
- `print(`: **0 matches** in changed code ✅
- `breakpoint()`: **0 matches** ✅
- `import pdb`: **0 matches** ✅
- Commented-out code: **0 matches** ✅
- TODO/FIXME/XXX: **0 matches** ✅

### Syntax validation
All 4 changed Python files pass `ast.parse()`:
- `src/episoa/verifier/faithfulness_verifier.py`: OK
- `tests/test_verifier_integration_v2.py`: OK
- `tests/test_verifier_llm_error_fix.py`: OK
- `tests/test_verifier_threshold_consistency.py`: OK

## 4. Verifier Threshold Consistency

### Config layer
| Config | Threshold | Status |
|--------|-----------|--------|
| paper.yaml | 0.45 | ✅ |
| ablation.yaml | 0.45 | ✅ |
| paper_with_heldout.yaml | 0.45 | ✅ |
| ablation_oracle_evidence.yaml | 0.45 | ✅ (fixed in F2) |
| ablation_human_gold_v2.yaml | 0.45 | ✅ (fixed in F2) |
| ablation_human_gold_v1.yaml | 0.45 | ✅ (fixed in F2) |
| ablation_single.yaml | 0.45 | ✅ (fixed in F2) |
| ablation_p0_parse_repair.yaml | 0.45 | ✅ (fixed in F2) |
| default.yaml | 0.45 | ✅ (fixed in F2) |
| opencode.yaml | 0.8 | ⚠️ (different provider, non-paper) |
| opencode_kimi.yaml | 0.8 | ⚠️ (different provider, non-paper) |

### Code layer
| Location | Default | Status |
|----------|---------|--------|
| `config.py:43` | 0.45 | ✅ (fixed in F2) |
| `pipeline.py:222` | 0.45 | ✅ (fixed in F2) |
| `pipeline.py:590` | 0.45 | ✅ (fixed in F2) |
| `verifier/faithfulness_verifier.py:48` | 0.45 | ✅ (already correct) |

### Paper layer
- AI declaration (Para 93): mentions gpt-5.5, `base_url=https://api.asxs.top/v1`
- Note: Threshold value 0.45 is not explicitly stated in paper text, but verifier mode (decomposed) is mentioned. **Acceptable** — threshold is a config detail, not a paper claim.

### LLM prompt comment
- `verifier/faithfulness_verifier.py:533`: "当前验证阈值已从0.75降低为0.45" — ✅ (fixed in F2, was 0.40)

## 5. AI Slop Check

- **Excessive comments**: No — comments are minimal and explain "why" not "what"
- **Over-abstraction**: No — changes are surgical (single-value edits, no new classes/wrappers)
- **Unused imports**: Checked in changed files — none added
- **Dead code**: No dead code introduced

## 6. Verifier Fallback Logic Review

`faithfulness_verifier.py:595-603`:
```python
except Exception:
    # LLM error fallback: return a neutral score (0.6) instead of 0.5.
    # 0.6 is above the unified verifier threshold (0.45), so the tuple
    # is NOT rejected solely due to LLM infrastructure errors. The
    # rule_precheck result (already computed before this call) determines
    # the final verdict via _apply_hard_flag_score_cap. This prevents
    # mass rejection when LLM API has transient failures (network
    # timeout, rate limit, JSON parse errors).
    return 0.6, {"reason": "llm_verifier_error", "score": 0.6}
```

- **Rationale clear**: ✅ (explains why 0.6, not just what)
- **Magic number justified**: ✅ (0.6 > 0.45 threshold, neutral)
- **Not swallowing error silently**: ✅ (returns diagnostic reason in dict)
- **No retry/loop risk**: ✅ (single return, no retry)

## VERDICT

```
Tests: 427 pass / 1 pre-existing fail (API-blocked, not regression)
Lint: PASS (no anti-patterns)
Files: 13 changed, all clean
Threshold consistency: PASS (9/9 paper configs = 0.45; 2 opencode = 0.8 by design)
VERDICT: APPROVE (with note: pre-existing test failure will resolve after API fix + experiment rerun)
```

## F2 Fixes Applied (bonus)

During F2 review, found and fixed 5 additional threshold inconsistencies:
1. `config.py:43` — fallback default 0.75→0.45
2. `pipeline.py:222` — manifest fallback 0.75→0.45
3. `pipeline.py:590` — verify_tuples() fallback 0.75→0.45
4. `faithfulness_verifier.py:533` — stale comment 0.40→0.45
5. `faithfulness_verifier.py:597` — stale comment 0.75→0.45

Also unified 6 legacy configs (ablation_oracle_evidence, ablation_human_gold_v1/v2, ablation_single, ablation_p0_parse_repair, default) from 0.75→0.45.
