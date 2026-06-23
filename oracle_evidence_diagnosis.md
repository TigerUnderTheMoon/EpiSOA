# Oracle Evidence Diagnosis: 0 Predictions Root Cause

## Summary
- **Setting**: `ablation_oracle_evidence`
- **Observed**: Num-Tuples=0, F1@0.3=0.0, ESR=0.0 (all zeros)
- **Expected**: Num-Tuples>0, F1≥full_soe (uses gold evidence IDs)

## Section 1: Observed Symptoms

### metrics.json
```json
{
  "Num-Tuples": 0,
  "Num-Tuples-All": 0,
  "Tuple-F1-semantic@0.3": 0.0,
  "ESR": 0.0,
  "UTR": 0.0
}
```

### schema_attribution_summary.json
```json
{
  "num_events_requested": 50,
  "num_events_processed": 50,
  "num_events_skipped": 0,
  "num_tuples_generated": <missing>,
  "parse_failed_events": ["E025", "E026", ..., "E050"]  // 26 events!
}
```

### candidate_soa_tuples.jsonl
- **129 lines** (candidates WERE generated)

### scoring_scope.json
- Only contains `excluded_prediction_count` and `excluded_event_ids`
- No candidate_count field

## Section 2: Pipeline Trace

### Stage 1: Evidence Selection (selector_mode="oracle")
- `select_oracle_first()` in `evidence_selector.py:171-218` ran successfully
- It read gold evidence IDs via `_oracle_evidence_ids_by_event(gold)` (pipeline.py:540, 1026-1054)
- Gold evidence IDs were matched against evidence_rows
- **Evidence was selected correctly** (129 candidates generated means attribution had input)

### Stage 2: Schema Attribution
- `run_schema_attribution()` processed all 50 events
- **26 events (E025-E050) had parse_failed_events** — LLM output parsing failed
- 24 events (E001-E024) succeeded, producing 129 candidates

### Stage 3: Verifier (THE BREAKING POINT)
- 129 candidates fed to `verify_tuples()`
- `verifier_mode="decomposed"`, `threshold=0.75` (from config)
- LLM verifier called on all 129 candidates
- **ALL 129 candidates rejected** (score < 0.75)
- Result: 0 verified tuples, 0 predictions

### Stage 4: Verifier Quality Gate
- `verifier_quality_gate.json` shows 0 before/after (all already rejected by verifier)

## Section 3: Root Cause

**The oracle_evidence 0-prediction issue is caused by the SAME verifier over-rejection bug affecting full_soe, NOT by an oracle selector bug.**

### Evidence:
1. 129 candidates were generated (attribution succeeded for 24/50 events)
2. 26 events had parse_failed_events (LLM output format issue, separate problem)
3. All 129 candidates were rejected by verifier (threshold 0.75 too high)
4. This is the same pattern as full_soe (146 candidates → 82 verified)

### Why oracle_evidence is worse than full_soe:
- full_soe: 146 candidates → 82 verified (56% pass rate)
- oracle_evidence: 129 candidates → 0 verified (0% pass rate)

The difference is that oracle_evidence uses gold evidence IDs, which may produce candidates with different text spans that the verifier handles differently. But the root cause is the verifier threshold + LLM error fallback, not the oracle selector.

### Secondary Issue: 26 parse_failed_events
- Events E025-E050 all failed LLM parse
- This is a separate LLM output format issue
- Even if verifier is fixed, these 26 events won't produce candidates
- This halves the potential tuples (only 24/50 events produce candidates)

## Section 4: Fix Recommendation

### Primary Fix: Verifier threshold + LLM error fallback (Task 8, 9)
- Lower config threshold from 0.75 to 0.45
- Fix LLM error fallback (line 596) to not default-reject
- This will allow oracle_evidence candidates to pass verification

### Secondary Fix: Parse failed events investigation
- Check `raw_llm_responses.jsonl` for E025-E050 to see why parse failed
- May need prompt format adjustment or JSON schema enforcement
- This is a separate issue from the 0-prediction bug

### No Fix Needed for Oracle Selector
- `select_oracle_first()` works correctly (129 candidates generated)
- `_oracle_evidence_ids_by_event()` correctly extracts gold evidence IDs
- The oracle selector is NOT broken

## Section 5: Expected Results After Fix

After Task 8 (verifier LLM error fix) + Task 9 (threshold unification):
- oracle_evidence should produce ≥100 tuples (from 129 candidates)
- F1@0.3 should be ≥0.5 (oracle uses gold evidence, should match gold well)
- ESR should be 1.0 (all evidence IDs are gold-sourced)

If oracle_evidence still produces 0 after verifier fix, investigate the 26 parse_failed_events as a separate issue.

---

Generated: 2026-06-23
Baseline commit: 28dfe504a9f149ec04dc221a989dcf66bd7c0093
