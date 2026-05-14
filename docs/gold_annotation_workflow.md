# Gold Annotation Workflow

Standardized workflow for gold annotation repair, expansion, and audit.
All scripts support `--max-events` to limit scope for rehearsal runs.

**IMPORTANT**: The canonical evidence namespace for gold annotation is
`data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl`.
Do NOT use `evidence_filtered.jsonl` to audit gold annotation — gold tuples
and chains reference evidence_ids from the repaired evidence namespace.

## Standard Workflow

### 1. Normalize Evidence Source Types

Ensure all evidence records have correct `source_type` field:

```bash
python scripts/normalize_evidence_source_type.py \
  --input data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --dry-run

# Apply changes (auto-backups original):
python scripts/normalize_evidence_source_type.py \
  --input data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

Mappings: `official→official`, `news→mainstream_news`, `public_social→social_media`,
`public_interaction→public_interaction`, `forum→forum`.
`public_web` is re-inferred from domain using `configs/source_detection.yaml` rules.

### 2. Normalize Chain IDs

Ensure all chain records have a deterministic `chain_id` field:

```bash
python scripts/normalize_chain_ids.py \
  --input data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --dry-run

# Apply changes (auto-backups original):
python scripts/normalize_chain_ids.py \
  --input data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl
```

Format: `CHAIN_{event_id}_{序号}` (e.g., `CHAIN_E001_001`).

### 3. Audit Gold Annotation

Full audit of the current gold dataset:

```bash
# Full 50-event audit
python scripts/audit_gold_annotation.py \
  --events data/pubevent_soa_lite/events.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl

# Limit to first 20 events (rehearsal)
python scripts/audit_gold_annotation.py --max-events 20

# Write report to file
python scripts/audit_gold_annotation.py --output audit_report.json
```

Exit code 0 = ready for final gold. Exit code 1 = issues found.

Checks performed:
- Event coverage
- Tuple count >= 3 per event
- Chain count >= 2 per event
- Duplicate candidate_ids
- Duplicate chain_ids
- Missing chain_ids
- Invalid sentiment values
- Invalid support_label values
- Missing evidence references
- Missing source_type

### 4. Build Annotation Expansion Plan

Identify events with insufficient tuple/chain counts:

```bash
python scripts/build_annotation_expansion_plan.py \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --max-events 50

# Customize thresholds
python scripts/build_annotation_expansion_plan.py --tuple-min 4 --chain-min 3
```

Output: `annotation_expansion_plan.jsonl` with P0/P1 priority and task type.

Priorities:
- **P0**: Both tuple and chain below threshold, or 0 tuples/chains
- **P1**: Only one dimension below threshold

Task types: `expand_tuples_and_chains`, `expand_tuples_only`, `expand_chains_only`

### 5. Run Targeted Expansion

Execute targeted annotation expansion for events in the plan.

Two modes are available:

**Rule-based (default)**: Fast, no API calls needed. Uses keyword matching and source-type templates.

```bash
python scripts/run_annotation_expansion.py
python scripts/run_annotation_expansion.py --max-events 20
```

**LLM-based (--use-llm)**: Higher quality, evidence-grounded candidates. Requires API access.

```bash
# Preview what would happen (dry-run)
python scripts/run_annotation_expansion.py --use-llm --dry-run

# LLM expansion with custom prompts and temperature
python scripts/run_annotation_expansion.py --use-llm \
  --config configs/paper.yaml \
  --tuple-prompt prompts/gold_tuple_expansion.md \
  --chain-prompt prompts/gold_chain_expansion.md \
  --temperature 0.2

# LLM expansion with rehearsal limit
python scripts/run_annotation_expansion.py --use-llm --max-events 10 \
  --timeout-seconds 60
```

When `--use-llm` is set but the LLM call fails, the script automatically falls back to rule-based expansion for that event.

Outputs delta files (does NOT overwrite original gold):
- `llm_gold_tuples_expansion_delta.jsonl`
- `llm_gold_event_chains_expansion_delta.jsonl`

### 6. Audit Expansion Delta

Verify delta files are safe to merge:

```bash
python scripts/audit_annotation_expansion_delta.py \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --delta-tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples_expansion_delta.jsonl \
  --delta-chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains_expansion_delta.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

Exit code 0 = delta is safe to merge. Exit code 1 = issues found.

### 7. Merge Expansion into Gold

Merge delta into gold (safety-gated — audit must pass first):

```bash
# Create merged files without overwriting originals
python scripts/merge_annotation_expansion.py \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --delta-tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples_expansion_delta.jsonl \
  --delta-chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains_expansion_delta.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl

# After reviewing merged files, commit to originals:
python scripts/merge_annotation_expansion.py \
  --tuples ... --chains ... --delta-tuples ... --delta-chains ... \
  --evidence ... --commit
```

The `--commit` flag:
1. Backs up original gold files (`*.bak_{timestamp}`)
2. Overwrites originals with merged content

### 8. Final Audit

Re-run audit after merge to confirm all checks pass:

```bash
python scripts/audit_gold_annotation.py --output final_audit.json
```

The report should show `ready_for_final_gold: true`.

### 9. Write Manifest

Generate or update the gold manifest:

```bash
python scripts/write_gold_manifest.py \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --version "v3_repaired_gold_final" \
  --quality-status final_audit.json
```

## Quick Run (Full 50-Event Rehearsal)

```bash
ANNOT_DIR="data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37"
EVIDENCE="data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl"
EVENTS="data/pubevent_soa_lite/events.jsonl"

# Step 1
python scripts/normalize_evidence_source_type.py --input "$EVIDENCE" --dry-run

# Step 2
python scripts/normalize_chain_ids.py --input "$ANNOT_DIR/llm_gold_event_chains.jsonl" --dry-run

# Step 3
python scripts/audit_gold_annotation.py \
  --events "$EVENTS" --evidence "$EVIDENCE" \
  --tuples "$ANNOT_DIR/llm_gold_tuples.jsonl" \
  --chains "$ANNOT_DIR/llm_gold_event_chains.jsonl" \
  --output "$ANNOT_DIR/audit_report.json"

# Step 4
python scripts/build_annotation_expansion_plan.py \
  --events "$EVENTS" --evidence "$EVIDENCE" \
  --tuples "$ANNOT_DIR/llm_gold_tuples.jsonl" \
  --chains "$ANNOT_DIR/llm_gold_event_chains.jsonl"

# Step 5 (if expansion needed)
python scripts/run_annotation_expansion.py

# Step 6
python scripts/audit_annotation_expansion_delta.py \
  --tuples "$ANNOT_DIR/llm_gold_tuples.jsonl" \
  --chains "$ANNOT_DIR/llm_gold_event_chains.jsonl" \
  --delta-tuples "$ANNOT_DIR/llm_gold_tuples_expansion_delta.jsonl" \
  --delta-chains "$ANNOT_DIR/llm_gold_event_chains_expansion_delta.jsonl" \
  --evidence "$EVIDENCE"

# Step 7
python scripts/merge_annotation_expansion.py \
  --tuples "$ANNOT_DIR/llm_gold_tuples.jsonl" \
  --chains "$ANNOT_DIR/llm_gold_event_chains.jsonl" \
  --delta-tuples "$ANNOT_DIR/llm_gold_tuples_expansion_delta.jsonl" \
  --delta-chains "$ANNOT_DIR/llm_gold_event_chains_expansion_delta.jsonl" \
  --evidence "$EVIDENCE"

# Step 8
python scripts/audit_gold_annotation.py --output "$ANNOT_DIR/final_audit.json"

# Step 9
python scripts/write_gold_manifest.py \
  --tuples "$ANNOT_DIR/llm_gold_tuples.jsonl" \
  --chains "$ANNOT_DIR/llm_gold_event_chains.jsonl" \
  --evidence "$EVIDENCE" \
  --quality-status "$ANNOT_DIR/final_audit.json"
```
