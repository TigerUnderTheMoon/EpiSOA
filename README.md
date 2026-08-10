# EpiSOA

EpiSOA is a reproducible research framework for Evidence-grounded Stakeholder Opinion Attribution in public events.

> **Implementation-status boundary:** The workflow below primarily describes the legacy `soe_v3` implementation. The frozen EpiSOA-EA v1.5 contract is defined in [`docs/method_framework.md`](docs/method_framework.md) and [`docs/annotation_guidelines.md`](docs/annotation_guidelines.md). The isolated `src/episoa/ea/` path contains offline Document Understanding, APCF/Fusion, Event Dossier, Gold, baseline-adapter, and evaluation tooling; this is synthetic-test implementation, not six-event Pilot evidence, human Gold, real-API results, or Formal paper readiness.

M5 starts from the frozen [`docs/m5_pilot_protocol.md`](docs/m5_pilot_protocol.md), the six-event rationale in [`docs/m5_event_selection.md`](docs/m5_event_selection.md), and the machine-readable registry [`configs/ea_pilot_events.yaml`](configs/ea_pilot_events.yaml). Gold sheets and adjudication rules are documented in [`docs/m5_gold_template_guide.md`](docs/m5_gold_template_guide.md). The auditable implementation, model, test, and file-hash snapshot is [`configs/ea_pre_pilot_freeze.yaml`](configs/ea_pre_pilot_freeze.yaml).

The core output schema is:

```text
<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>
```

Formal pipeline predictions also carry audit fields for stakeholder-canonical
extraction: `stakeholder_cluster_id`, `stakeholder_aliases`,
`canonical_tuple`, `opinion_split_reason`,
`stakeholder_candidate_match_status`, `matched_stakeholder_candidate`,
`stage_candidate_ids`, and `attribution_pass`.

## Parallel EpiSOA-EA v1.5 path

The EA path is isolated from legacy data, caches, schemas, and outputs. Its offline stages are:

```text
python -m episoa.cli prepare-ea
python -m episoa.cli run-ea --stage m2
python -m episoa.cli run-ea --stage m3
python -m episoa.cli run-ea --stage fusion --fusion-method apcf
python -m episoa.cli run-ea --stage dossier
```

Running `run-ea` without `--stage` executes M2 → M3 → APCF → Dossier and blocks if prepared Documents are absent. Exact, Embedding, and LLM Pairwise fusion outputs are experiment artifacts and do not overwrite the formal APCF Canonical/Dossier files. Real API execution and the six-event Pilot remain intentionally blocked by missing Pilot inputs and frozen-readiness gates.

## Event-First Paper Workflow

1. Formal event registry construction
2. Evidence collection with C-FSM
3. Evidence normalization and annotation sheet generation
4. LLM preannotation as silver data, human adjudication, and human_gold export
5. Experiment execution and evaluation

The formal pipeline starts directly from accepted concrete public events in:

```text
data/pubevent_soa_lite/events.jsonl
```

`events.jsonl` is the event registry. It must contain only accepted concrete public events with factual locations, time windows, triggers, structured anchor entities, anchor URLs, source scopes, and query seeds.

## Data Flow

```text
data/pubevent_soa_lite/
|-- events.jsonl
|-- raw/
|-- interim/
|-- annotation_fulltext_stakeholder_canonical_nonheldout/
|   |-- llm_gold_tuples.jsonl
|   `-- llm_gold_event_chains.jsonl
|-- human_gold_v2_stakeholder_canonical/
|   `-- independent/
|       |-- annotator_A/humanA_tuple_adjudication_sheet.csv
|       |-- annotator_B/humanB_tuple_adjudication_sheet.csv
|       `-- annotator_C/humanC_tuple_adjudication_sheet.csv
|-- human_gold_v2/
|   |-- human_gold_tuples_v2.jsonl
|   `-- human_gold_event_chains_v2.jsonl
|-- evidence_v3_repaired_plus_low37.jsonl
`-- README.md
```

`annotation_fulltext_stakeholder_canonical_nonheldout/llm_gold_*` files are LLM
preannotation artifacts. They are silver/pseudo-gold, not final human-verified
gold. Use `scripts/export_silver_benchmark.py`,
`scripts/build_human_adjudication_sheet.py`,
`scripts/convert_adjudication_to_human_gold.py`, and
`scripts/audit_human_gold.py` to create `human_gold_v2` before final paper
experiments.

Formal data flow:

```text
events.jsonl
  -> scripts/collect_evidence.py
  -> scripts/normalize_evidence.py
  -> scripts/make_annotation_sheet.py
  -> scripts/run_llm_gold_preannotation.py
  -> scripts/export_silver_benchmark.py
  -> scripts/build_human_adjudication_sheet.py
  -> scripts/convert_adjudication_to_human_gold.py
  -> scripts/audit_human_gold.py
  -> scripts/validate_gold_dataset.py
  -> scripts/run_paper_experiment.py
```

Generated raw, interim, annotation, evidence, gold, and output files are intentionally ignored by git. Use `scripts/reset_workspace.py` to return the repository to an empty data skeleton.

## SOE v3 Main Method

The paper main method is `soe_v3`. It does not use a GNN; the rule-derived
evidence graph remains an auditable skeleton. The main path uses:

- `coverage_optimized` evidence selection.
- Two-pass SOA attribution: `stage_extract` first writes stage-level candidates
  to `stage_soa_candidates.jsonl`; `canonical_merge` then writes
  stakeholder-canonical final tuples to `candidate_soa_tuples.jsonl`.
- `soe_graph/` materialization from final stakeholder, opinion, sentiment,
  stage, and evidence-span nodes.
- Decomposed field-level verifier diagnostics.

The formal pipeline no longer asks the LLM for a fixed number of tuples per
event. `SchemaAttributor` runs with
`attribution_mode=stakeholder_canonical`:

- It identifies distinct event-level stakeholder clusters from graph
  stakeholder candidates and selected evidence.
- It emits one canonical tuple per evidence-supported stakeholder by default.
- It merges multiple evidence items for the same stakeholder/opinion into one
  tuple by collecting all valid `evidence_ids`.
- It allows multiple tuples for the same `stakeholder_cluster_id` only when
  the opinions/actions differ and `opinion_split_reason` is non-empty.
- It allows evidence-supported stakeholders missing from graph candidates, but
  marks them as `stakeholder_candidate_match_status=unmatched` for audit.

`max_tuples_per_event` may still appear in legacy config files for compatibility,
but it is no longer a formal attribution target or cap. Pipeline manifests write
`tuple_limit_policy: none` and
`max_tuples_per_event_deprecated_noop` to make this explicit.

Evidence selection is coverage-optimized in the main method. The selector
balances event relevance, chain stage score, stakeholder coverage, stage
coverage, source-family coverage, opinion-bearing signal, and quality score,
then penalizes near-duplicate title/text evidence. Per-event diagnostics include
covered/uncovered stakeholder candidates, selected evidence IDs, source/stage
coverage, redundancy penalty counts, and objective components.

## Human Gold Review Sheets

Independent human review tuple sheets are intentionally annotator-specific:

```text
data/pubevent_soa_lite/human_gold_v2_stakeholder_canonical/independent/
|-- annotator_A/humanA_tuple_adjudication_sheet.csv
|-- annotator_B/humanB_tuple_adjudication_sheet.csv
`-- annotator_C/humanC_tuple_adjudication_sheet.csv
```

The chain review sheet remains `human_chain_adjudication_sheet.csv` inside each
annotator directory. The annotator-specific tuple filenames are pure renames of
the older per-directory `human_tuple_adjudication_sheet.csv` convention, so each
reviewer's file is visible in diffs and handoffs.

## Evidence Collection Scope

The C-FSM collector performs cross-source public web retrieval over publicly accessible and search-indexed evidence. It is not platform-specific login-based crawling.

`source_scope` uses source categories:

- `news`: publicly accessible news pages
- `official`: public government, institutional, or organization pages
- `forum`: public forum and discussion pages
- `public_social`: public social-media-related pages, search-indexed post snippets, or social-media content quoted by news, forums, or aggregators
- `public_web`: other publicly accessible web pages

`public_social` does not include non-public content that is only visible after signing in, internal comment areas, short-video comment threads, or complete note data from platforms such as Douyin, Xiaohongshu, or Weibo.

## Commands

Validate event registry:

```bash
python scripts/validate_events.py
```

Check full paper readiness:

```bash
python scripts/validate_paper_data.py
python -m episoa.cli paper-status
```

Run fast tests:

```bash
python -m pytest -q
```

Use `python -m pytest` rather than bare `pytest` in this Windows workspace so
repo-local `scripts.*` imports resolve consistently.

Run data preparation after `events_ready=true`:

```bash
python scripts/collect_evidence.py
python scripts/normalize_evidence.py
python scripts/make_annotation_sheet.py
python scripts/run_llm_gold_preannotation.py
python scripts/export_silver_benchmark.py
python scripts/build_human_adjudication_sheet.py
# after human review:
python scripts/convert_adjudication_to_human_gold.py
python scripts/audit_human_gold.py
python scripts/validate_gold_dataset.py
python scripts/inspect_gold_samples.py --num-events 3 --seed 42
```

`scripts/collect_evidence.py` uses the heuristic C-FSM seed expansion planner
configured through `configs/collector.yaml`. It writes planner diagnostics to
`data/pubevent_soa_lite/interim/query_planner_debug.json` and the live coverage
snapshot to `data/pubevent_soa_lite/interim/coverage.json`, then continues
through the coverage repair-round mechanism. Temporal-stage coverage is handled
by the existing repair diagnostics and reported as
`literal_string_match_legacy`.

Resume an interrupted collection without repeating completed events:

```bash
python scripts/collect_evidence.py --resume
```

`coverage.json` is a JSON snapshot; read it with `json.load`, not as JSONL.

Run paper experiments after `paper_data_ready=true`:

```bash
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation.yaml --force
```

Use `--force` for the paper reproduction ablation run:

```bash
python scripts/run_ablation.py --config configs/ablation.yaml --force
```

`run_ablation.py` runs every configured setting. `--force` first removes
existing per-setting output directories so the aggregate CSV cannot read stale
artifacts.

Or via the CLI entry point:

```bash
python -m episoa.cli run-ablation --config configs/ablation.yaml
python -m episoa.cli run-ablation --config configs/ablation.yaml --force
```

Reset generated artifacts:

```bash
python scripts/reset_workspace.py
```

## API Configuration

API settings can be provided in YAML or environment variables. Runtime status prints only the source and a masked key; it never prints the full key.

Example model configuration:

```yaml
model:
  mode: real
  llm_mode: real
  llm_model: gpt-5.5
  api_key_env: OPENAI_API_KEY
  base_url: "https://api.openai.com/v1"
  timeout_seconds: 60
  max_retries: 2
  temperature: 0
```

Example search configuration:

```yaml
search:
  provider: custom
  api_key_env: SEARCH_API_KEY
  base_url_env: SEARCH_BASE_URL
collector:
  source_types:
    - news
    - official
    - forum
    - public_social
    - public_web
```

## Outputs

Formal runs write artifacts to:

```text
outputs/runs_human_gold_v2/{run_id}/
|-- config.yaml
|-- predictions.jsonl
|-- candidate_soa_tuples.jsonl
|-- verified_soa_tuples.jsonl
|-- metrics.json
|-- summary.json
|-- main_results.csv
|-- retrieval_results.csv
|-- verifier_results.csv
|-- human_eval_sheet.csv
`-- case_studies.jsonl
```

Ablation aggregates are written under `outputs/runs_human_gold_v2/`, with one
`ablation_{setting}/` directory per setting.
