# EpiSOA

EpiSOA is a reproducible research project for Evidence-grounded Stakeholder Opinion Attribution in public events.

The core output schema is:

```text
<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>
```

## Five-Stage Paper Workflow

1. Topic-to-event instantiation
2. Evidence collection with C-FSM
3. Gold test-set construction through human annotation
4. Experiment execution and automatic evaluation
5. Human evaluation and case analysis

## Evidence Collection Scope

The C-FSM collector performs cross-source public web retrieval over publicly accessible and search-indexed evidence. It is not platform-specific login-based crawling.

`source_scope` uses source categories, not private platform access modes:

- `news`: publicly accessible news pages
- `official`: public government, institutional, or organization pages
- `forum`: public forum and discussion pages
- `public_social`: public social-media-related pages, search-indexed post snippets, or social-media content quoted by news, forums, or aggregators
- `public_web`: other publicly accessible web pages

`public_social` does not include non-public content that is only visible after signing in, internal comment areas, short-video comment threads, or complete note data from platforms such as Douyin, Xiaohongshu, or Weibo. The project does not bypass website access controls and only stores traceable candidate evidence from public web pages.

Recommended method wording: "cross-source public web retrieval", "publicly accessible and search-indexed evidence", and "not platform-specific login-based crawling".

## Data Flow

```text
data/pubevent_soa_lite/
|-- topic_seeds.jsonl
|-- candidate_event_instances.jsonl
|-- events.jsonl
|-- raw/
|   `-- raw_posts.jsonl
|-- interim/
|   |-- evidence_candidates.jsonl
|   |-- duplicate_report.csv
|   `-- collection_coverage_report.json
|-- evidence.jsonl
|-- annotation/
|   |-- annotation_sheet.csv
|   `-- annotation_guideline.md
|-- gold_tuples.jsonl
|-- gold_event_chains.jsonl
`-- README.md
```

The upstream event data is now three-layered:

- `topic_seeds.jsonl` stores topic-level issue seeds. The current 50 legacy records were migrated here from the old `events.jsonl`; they preserve the original coverage design but are not concrete public events.
- `candidate_event_instances.jsonl` stores manually discovered and screened candidate concrete events.
- `events.jsonl` stores only accepted concrete formal event instances. It may be empty until human screening is complete.

`topic seed != concrete event`. Topic seeds often contain placeholders such as "某市", "某地", "某校", "某医院", or "某平台"; such records are invalid in formal `events.jsonl`.

Use `public_social` in `source_scope`; do not use the legacy `social_media` label.

Formal `gold_tuples.jsonl` and `gold_event_chains.jsonl` can only be built from accepted concrete events and their evidence. The earlier 10-event gold pilot is now only a topic-level diagnostic pilot and must not be treated as formal gold.

Legacy topic-level raw posts, evidence, annotation sheets, and pilot outputs are archived under `data/pubevent_soa_lite/discovery/`. That directory is a discovery corpus for finding concrete candidate events and diagnosing prompts; formal validators and paper experiments do not read it.

`gold_tuples.jsonl` and `gold_event_chains.jsonl` must be created only after `evidence.jsonl` has been produced from collected raw posts and manually annotated.

## Commands

Validate current data state:

```bash
python scripts/validate_paper_data.py
python scripts/validate_event_instantiation_data.py
python -m episoa.cli paper-status
```

Run the data-preparation interfaces:

```bash
python scripts/migrate_events_to_topic_seeds.py
python scripts/make_candidate_event_instance_sheet.py
python scripts/promote_candidate_events.py
python scripts/collect_evidence.py
python scripts/normalize_evidence.py
python scripts/make_annotation_sheet.py
python scripts/build_gold_review_sheets.py
python scripts/run_llm_gold_preannotation.py
python scripts/convert_review_sheets_to_gold.py
python scripts/validate_gold_dataset.py
python scripts/inspect_gold_samples.py --num-events 3 --seed 42
```

Gold construction uses LLM preannotation only as review assistance. Formal
`gold_tuples.jsonl` and `gold_event_chains.jsonl` are exported only from
human-reviewed sheets with final decisions such as `accept`, `edit`, `add_new`,
or `merge`; `reject` and unreviewed rows are excluded.

`run_llm_gold_preannotation.py` defaults to a one-event smoke run. Use
`--all-events` for the full formal LLM preannotation pass.

Check UTF-8 display and replacement-character damage without rewriting data:

```bash
python scripts/check_utf8_display.py
```

On Windows, apparent strings such as `鏌愬競` or `鈥揺vent` are often console display issues rather than file corruption. Prefer VS Code, Python, or another UTF-8-aware editor for JSONL/CSV/Markdown inspection. For PowerShell sessions, set UTF-8 output before printing Chinese text:

```powershell
chcp 65001
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::UTF8
```

Avoid using `type` or older terminal sessions as the source of truth for file encoding. If `scripts/check_utf8_display.py` reports `�` replacement characters, treat them as evidence text already lost during collection or earlier decoding; the checker reports them but does not rewrite source data.

## API Configuration

EpiSOA supports two API configuration styles.

For a local private project, you may write API settings directly in YAML:

```yaml
model:
  mode: real
  llm_mode: real
  llm_model: gpt-4o-mini
  embedding_model: mock-embedding
  reranker_model: mock-reranker
  api_key: "your-llm-api-key"
  api_key_env: OPENAI_API_KEY
  base_url: "https://your-llm-api-base-url/v1"
  timeout_seconds: 60
  max_retries: 2
  temperature: 0
```

Search/collection API settings can be kept in `configs/collector.yaml`:

```yaml
search:
  provider: custom
  api_key: "your-search-api-key"
  api_key_env: SEARCH_API_KEY
  base_url: "https://your-search-api-base-url/v1"
  timeout_seconds: 30
  max_retries: 2
collector:
  source_types:
    - news
    - official
    - forum
    - public_social
    - public_web
```

For public repositories or team collaboration, keep `api_key` and `base_url` empty and use environment variables through `api_key_env` and `base_url_env`.

Resolution order:

1. YAML `api_key` if non-empty.
2. Environment variable named by `api_key_env`.
3. YAML `base_url` if non-empty.
4. Environment variable named by `base_url_env`.

Runtime status prints only the source and a masked key such as `sk-1***abcd`; it never prints the full key.

Run paper experiments after `paper_data_ready=true`:

```bash
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation.yaml
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

## What Not To Commit

Do not commit generated run artifacts, caches, logs, `.env`, temporary outputs, or historical experiment results.
