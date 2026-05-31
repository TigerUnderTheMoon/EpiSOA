# EpiSOA Stage 1-9 Reproducibility Checklist

## Stage 1-3 Evidence Base

```bash
python scripts/validate_events.py
python scripts/collect_evidence.py --resume
python scripts/normalize_evidence.py
python scripts/audit_cross_source_support.py
```

Expected guardrails: `events.jsonl` contains frozen `split`, `held_out`, `registry_version`, and `registered_at`; test events must be `held_out=true`; cross-source audit routes single-source rows to human review.

## Stage 4 LLM Pre-annotation

```bash
python scripts/run_llm_gold_preannotation.py --config configs/paper.yaml --all-events
python scripts/export_silver_benchmark.py
```

Required artifacts: `llm_preannotation_report.json`, `llm_preannotation_audit.jsonl`, `llm_preannotation_prompt_manifest.json`, and raw responses. These are silver artifacts only.

## Stage 5-7 Human Gold

```bash
python scripts/build_human_adjudication_sheet.py \
  --silver-tuples data/pubevent_soa_lite/annotation_fulltext_stakeholder_canonical_nonheldout/llm_gold_tuples.jsonl \
  --silver-chains data/pubevent_soa_lite/annotation_fulltext_stakeholder_canonical_nonheldout/llm_gold_event_chains.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --output-dir data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical
python scripts/build_independent_human_adjudication.py prepare \
  --tuple-sheet data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/human_tuple_adjudication_sheet.csv \
  --chain-sheet data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/human_chain_adjudication_sheet.csv \
  --output-dir data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent
python scripts/build_independent_human_adjudication.py audit \
  --tuple-sheets data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_A/humanA_tuple_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_B/humanB_tuple_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_C/humanC_tuple_adjudication_sheet.csv \
  --chain-sheets data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_A/human_chain_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_B/human_chain_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_C/human_chain_adjudication_sheet.csv \
  --output-dir data/pubevent_soa_lite/human_gold_v2/independent_audit
python scripts/build_independent_human_adjudication.py consensus \
  --tuple-sheets data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_A/humanA_tuple_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_B/humanB_tuple_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_C/humanC_tuple_adjudication_sheet.csv \
  --chain-sheets data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_A/human_chain_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_B/human_chain_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_C/human_chain_adjudication_sheet.csv \
  --output-dir data/pubevent_soa_lite/human_gold_v2
python scripts/convert_adjudication_to_human_gold.py \
  --tuple-sheet data/pubevent_soa_lite/human_gold_v2/adjudicated_human_tuple_sheet.csv \
  --chain-sheet data/pubevent_soa_lite/human_gold_v2/adjudicated_human_chain_sheet.csv \
  --output-dir data/pubevent_soa_lite/human_gold_v2 \
  --dataset-version v2 \
  --include-evidence-spans \
  --iaa-report data/pubevent_soa_lite/human_gold_v2/independent_audit/independent_annotation_iaa_report.json
python scripts/audit_human_gold.py --tuples data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl --chains data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl --manifest data/pubevent_soa_lite/human_gold_v2/human_gold_manifest_v2.json --output-dir data/pubevent_soa_lite/human_gold_v2
python scripts/validate_gold_dataset.py \
  --gold-tuples data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl \
  --gold-event-chains data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --events data/pubevent_soa_lite/events.jsonl
```

Only `adjudication_status=adjudicated_final` rows enter final gold.
Independent tuple review sheets are named per annotator (`humanA_tuple_adjudication_sheet.csv`,
`humanB_tuple_adjudication_sheet.csv`, `humanC_tuple_adjudication_sheet.csv`);
chain sheets keep the shared `human_chain_adjudication_sheet.csv` filename
inside each annotator directory.

## Stage 8 Paper/Ablation

```bash
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation.yaml --force
```

Every setting writes input and prompt manifests with seed, git commit, model configuration, and flags.

## Stage 9 Benchmark/Probe

```bash
python scripts/build_benchmark_tasks.py --events data/pubevent_soa_lite/events.jsonl --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl --tuples data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl --chains data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl --output-dir data/benchmark/pubevent_soa_lite_human_gold_v2 --make-splits
python scripts/run_benchmark_eval.py --benchmark-dir data/benchmark/pubevent_soa_lite_human_gold_v2/splits/test --config configs/ablation.yaml --output-dir outputs/benchmark_runs/pubevent-soa-lite-human-gold-v2-test_gpt-5.5 --resume
```

The benchmark builder uses Stage 1 registry splits. Random splits require explicit `--allow-random-splits` and are not paper-grade.
The current human_gold_v2 test split has no human gold tuple/chain labels, so
test-split benchmark eval is an API/task smoke check until held-out gold exists.
