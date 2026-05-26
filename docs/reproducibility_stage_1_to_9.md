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
python scripts/build_human_adjudication_sheet.py
python scripts/build_independent_human_adjudication.py prepare
python scripts/build_independent_human_adjudication.py audit \
  --tuple-sheets data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_A/humanA_tuple_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_B/humanB_tuple_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_C/humanC_tuple_adjudication_sheet.csv \
  --chain-sheets data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_A/human_chain_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_B/human_chain_adjudication_sheet.csv,data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/annotator_C/human_chain_adjudication_sheet.csv
python scripts/convert_adjudication_to_human_gold.py --tuple-sheet <adjudicated_tuple.csv> --chain-sheet <adjudicated_chain.csv> --output-dir data/pubevent_soa_lite/human_gold_v2
python scripts/audit_human_gold.py --tuples data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl --chains data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl --manifest data/pubevent_soa_lite/human_gold_v2/human_gold_manifest_v2.json --output-dir data/pubevent_soa_lite/human_gold_v2
```

Only `adjudication_status=adjudicated_final` rows enter final gold.
Independent tuple review sheets are named per annotator (`humanA_tuple_adjudication_sheet.csv`,
`humanB_tuple_adjudication_sheet.csv`, `humanC_tuple_adjudication_sheet.csv`);
chain sheets keep the shared `human_chain_adjudication_sheet.csv` filename
inside each annotator directory.

## Stage 8 Paper/Ablation

```bash
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation_human_gold_v2.yaml --force
```

Every setting writes input and prompt manifests with seed, git commit, model configuration, and flags.

## Stage 9 Benchmark/Probe

```bash
python scripts/build_benchmark_tasks.py --events data/pubevent_soa_lite/events.jsonl --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl --tuples data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl --chains data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl --output-dir data/benchmark/pubevent_soa_lite_human_gold_v2 --make-splits
python scripts/run_benchmark_eval.py --benchmark-dir data/benchmark/pubevent_soa_lite_human_gold_v2 --config configs/paper.yaml
```

The benchmark builder uses Stage 1 registry splits. Random splits require explicit `--allow-random-splits` and are not paper-grade.
