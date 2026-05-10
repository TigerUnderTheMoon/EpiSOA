# EpiSOA

EpiSOA is a reproducible research framework for Evidence-grounded Stakeholder Opinion Attribution in public events.

The core output schema is:

```text
<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>
```

## Event-First Paper Workflow

1. Formal event registry construction
2. Evidence collection with C-FSM
3. Evidence normalization and annotation sheet generation
4. LLM preannotation, human review, and gold export
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
|-- annotation/
|-- evidence.jsonl
|-- gold_tuples.jsonl
|-- gold_event_chains.jsonl
`-- README.md
```

Formal data flow:

```text
events.jsonl
  -> scripts/collect_evidence.py
  -> scripts/normalize_evidence.py
  -> scripts/make_annotation_sheet.py
  -> scripts/run_llm_gold_preannotation.py
  -> scripts/build_gold_review_sheets.py
  -> scripts/convert_review_sheets_to_gold.py
  -> scripts/validate_gold_dataset.py
  -> scripts/run_paper_experiment.py
```

Generated raw, interim, annotation, evidence, gold, and output files are intentionally ignored by git. Use `scripts/reset_workspace.py` to return the repository to an empty data skeleton.

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

Run data preparation after `events_ready=true`:

```bash
python scripts/collect_evidence.py
python scripts/normalize_evidence.py
python scripts/make_annotation_sheet.py
python scripts/run_llm_gold_preannotation.py
python scripts/build_gold_review_sheets.py
python scripts/convert_review_sheets_to_gold.py
python scripts/validate_gold_dataset.py
python scripts/inspect_gold_samples.py --num-events 3 --seed 42
```

Run paper experiments after `paper_data_ready=true`:

```bash
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation.yaml
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
  llm_model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  base_url: "https://your-llm-api-base-url/v1"
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
outputs/runs/{run_id}/
|-- config.yaml
|-- predictions.jsonl
|-- candidate_soa_tuples.jsonl
|-- verified_soa_tuples.jsonl
|-- metrics.json
|-- summary.json
|-- main_results.csv
|-- ablation_results.csv
|-- retrieval_results.csv
|-- verifier_results.csv
|-- human_eval_sheet.csv
`-- case_studies.jsonl
```
