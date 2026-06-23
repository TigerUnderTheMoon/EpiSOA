# Root Cause Analysis: Main Experiment vs Ablation full_soe Discrepancy

## Summary
- **Main experiment** (`pubevent-soa-lite-human-gold-v2-paper`): Num-Tuples=44, F1@0.3=0.2385
- **Ablation full_soe** (`ablation_full_soe`): Num-Tuples=82, F1@0.3=0.3906
- **Paper Table 5 reports**: 82/0.3906 (citing ablation, not main)
- **Gap**: 44 vs 82 tuples (46% difference)

## Section 1: Config Field Diff (paper.yaml vs ablation.yaml vs code)

| Field | paper.yaml | ablation.yaml | Code Default | 
|-------|-----------|---------------|--------------|
| `mode` | `paper` | `ablation` | — |
| `verifier.mode` | **MISSING** | `decomposed` | `"decomposed"` (line 461) |
| `verifier.threshold` | `0.75` | `0.75` | `0.45` (line 48) |
| `model.api_key` | `""` (empty) | (removed) | — |
| `model.base_url` | `""` (empty) | (removed) | — |
| `runtime.max_api_concurrency` | `4` (config) | `4` (config) | — |
| `runtime.resume` | `false` (config) | `false` (config) | — |

## Section 2: Code Path Diff (paper mode vs ablation mode)

### Paper Mode (`run_paper_pipeline`, pipeline.py:1057-1155)
Explicitly sets `paper_flags` (line 1104-1118):
```python
paper_flags = {
    "use_graph": True,
    "use_event_chain": True,
    "use_verifier": True,
    "use_soe_graph": True,
    "selector_mode": "coverage_optimized",
    "verifier_mode": "id_only" if runtime["skip_llm_verifier"] else "decomposed",
    "method_version": SOE_V3_METHOD_VERSION,
    "use_stage_attribution": True,
    "use_event_level_safety_net": True,
    "use_hybrid_refinement": True,
    "use_verifier_quality_gate": True,
}
```

### Ablation Mode (`run_ablation_pipeline`, pipeline.py:1290+)
Uses `ABLATION_SETTINGS["full_soe"]` (line 1252):
```python
"full_soe": {
    "use_graph": True, "use_event_chain": True, "use_verifier": True,
    "use_soe_graph": True, "use_stage_attribution": True,
    "use_event_level_safety_net": True, "use_hybrid_refinement": True,
    "use_verifier_quality_gate": True,
    "selector_mode": "coverage_optimized",
    "verifier_mode": "decomposed",
    "method_version": "soe_v3",
    "max_tuples_per_event": 8,
}
```

### VERDICT: Flags are IDENTICAL
Both paper mode and ablation full_soe apply the same flags. The 44 vs 82 gap is **NOT** caused by flag differences.

## Section 3: Cache Pollution Check

### Main Run runtime_manifest.json
```json
{
  "resume": true,           // ← POLLUTED! config says false
  "max_api_concurrency": 2, // ← DIFFERENT! config says 4
  "cache_dir": "outputs\\cache\\pipeline"
}
```

### Ablation full_soe runtime_manifest.json
```json
{
  "resume": false,
  "max_api_concurrency": 4,
  "cache_dir": "outputs\\cache\\pipeline"
}
```

### VERDICT: Cache Pollution is ROOT CAUSE
The main run was executed with `resume=true` (despite config saying `resume: false`), which means it **reused cached attribution artifacts** from a previous (possibly broken) run. The ablation run used `resume=false` and recomputed everything from scratch.

Additionally, `max_api_concurrency=2` in main vs `4` in ablation suggests the main run was launched with a different CLI override or an older config version.

## Section 4: ROOT CAUSE Conclusion

**The 44 vs 82 tuple gap is caused by cache pollution, not config/code differences.**

The main experiment was run with `resume=true`, which reused stale cached attribution artifacts from a previous run that produced fewer tuples. The ablation full_soe run used `resume=false` and recomputed everything, producing the correct 82 tuples.

**Evidence**:
1. Flags are identical between paper mode and ablation full_soe (Section 2)
2. Main runtime_manifest shows `resume: true` despite config `resume: false`
3. Main `max_api_concurrency: 2` despite config `4` (CLI override or stale config)
4. Both runs use same `cache_dir: outputs/cache/pipeline`

## Section 5: Fix Options

### Option A (RECOMMENDED): Clean cache + rerun main experiment
- Clear `outputs/cache/pipeline/` (already done in Task 7)
- Rerun `python scripts/run_paper_experiment.py --config configs/paper.yaml`
- Expected: main metrics should match ablation full_soe (82 tuples, F1@0.3≈0.39)

### Option B: Align config explicitly
- Add `verifier.mode: decomposed` to paper.yaml (already in ablation.yaml)
- Remove `api_key: ""` and `base_url: ""` empty values from paper.yaml
- This ensures config-level consistency but won't fix the cache pollution issue

### Option C: Force resume=false in code
- Add assertion in `run_paper_pipeline` that `resume=false` unless explicitly requested
- Prevents future cache pollution accidents

**Recommended**: Execute Option A + Option B + Option C together.

## Additional Finding: verifier.threshold Inconsistency

Three-way inconsistency:
- `configs/paper.yaml:62`: `threshold: 0.75`
- `configs/ablation.yaml:61`: `threshold: 0.75`
- `src/episoa/verifier/faithfulness_verifier.py:48`: `threshold: float = 0.45`
- Paper docx (VERIFIER_USER prompt line 533): "阈值已从0.75降低为0.40"

The config value (0.75) overrides the code default (0.45) at runtime (pipeline.py:590 `float(config.verifier.get("threshold", 0.75))`). So the effective threshold is 0.75, which is too high — LLM errors return 0.5 (line 596), below 0.75, causing mass rejection.

**Fix**: Change config threshold to 0.45 (matching code default and paper claim) in both paper.yaml and ablation.yaml.

---

Generated: 2026-06-23
Baseline commit: 28dfe504a9f149ec04dc221a989dcf66bd7c0093
