# PubEvent-SOA Lite Data Directory

This directory follows the five-stage paper data flow.

## Step 1: Topic-to-Event Instantiation

This directory separates topic seeds from concrete formal events:

```text
topic_seeds.jsonl
candidate_event_instances.jsonl
events.jsonl
```

`topic_seeds.jsonl` contains the 50 legacy topic-level records migrated from the old `events.jsonl`. They describe public issue templates and may use placeholders such as "某市", "某地", "某校", "某医院", or "某平台". They are not formal events.

`candidate_event_instances.jsonl` is for manually discovered candidate concrete events. Candidates can be rejected or accepted after screening.

`events.jsonl` is reserved for accepted concrete formal event instances only. It may be empty while topic-to-event instantiation is incomplete. Do not copy topic seeds back into `events.jsonl`.

Run:

```bash
python scripts/migrate_events_to_topic_seeds.py
python scripts/make_candidate_event_instance_sheet.py
python scripts/promote_candidate_events.py
python scripts/validate_event_instantiation_data.py
```

Formal gold data can only be based on accepted concrete events. The earlier 10-event gold pilot should be treated as a topic-level diagnostic pilot, not formal gold.

## Discovery Corpus

Legacy topic-level outputs are archived in:

```text
discovery/
|-- topic_raw_posts.jsonl
|-- topic_evidence.jsonl
|-- topic_annotation/
`-- topic_pilot/
```

These files support topic-to-event discovery, concrete candidate discovery, and diagnostic analysis only. They are not formal paper data. Formal scripts read `events.jsonl`, `raw/raw_posts.jsonl`, `evidence.jsonl`, `gold_tuples.jsonl`, and `gold_event_chains.jsonl`; they do not read `discovery/`.

After the archive step, formal `events.jsonl`, formal `evidence.jsonl`, and formal gold files remain empty until accepted concrete event instances are promoted.

## Step 2: Evidence Collection

Run:

```bash
python scripts/collect_evidence.py
```

Input:

```text
events.jsonl
```

`events.jsonl` must contain accepted concrete events. If it is empty, collection is blocked with a message directing editors back to the instantiation stage.

Output:

```text
raw/raw_posts.jsonl
```

The C-FSM collector performs cross-source public web retrieval. It collects publicly accessible and search-indexed candidate evidence only.

`source_scope` should use:

- `news`
- `official`
- `forum`
- `public_social`
- `public_web`

`public_social` means public social-media-related pages, indexed post snippets, or social-media content quoted by public news, forum, or aggregator pages. It excludes non-public sign-in-only content, internal comment areas, short-video comment threads, and complete note data from platforms such as Douyin, Xiaohongshu, or Weibo.

Use `public_social`, not the legacy `social_media` value.

The collector is not platform-specific login-based crawling and does not bypass website access controls. If live collection is not configured, it writes query planning and coverage diagnostics without fabricating raw posts.

## Step 3: Normalize Evidence

Run:

```bash
python scripts/normalize_evidence.py
```

Input:

```text
raw/raw_posts.jsonl
```

Output:

```text
evidence.jsonl
```

`evidence.jsonl` is the cleaned, de-duplicated, traceable evidence pool.

## Step 4: Evidence-Level Annotation Sheet

Run:

```bash
python scripts/make_annotation_sheet.py
```

Output:

```text
annotation/annotation_sheet.csv
```

This sheet is for evidence-level screening and rough tuple notes. It reads `evidence.jsonl`, not `evidence_filtered.jsonl`.

Use `is_relevant` for evidence-level decisions such as `yes`, `no`, `duplicate`, or `irrelevant`. Do not use `irrelevant` as a final gold tuple support label.

## Step 5: Gold Review Sheets

Build reproducible human review sheets:

```bash
python scripts/build_gold_review_sheets.py
```

Outputs:

```text
annotation/gold_tuple_review_sheet.csv
annotation/gold_chain_review_sheet.csv
annotation/gold_review_summary.json
```

The tuple and chain review sheets are organized by `event_id`. If no system candidate tuples or chains are available, the command still creates blank templates for every event.

Optional LLM preannotation:

```bash
python scripts/run_llm_gold_preannotation.py
```

Outputs:

```text
annotation/llm_gold_tuples.jsonl
annotation/llm_gold_event_chains.jsonl
annotation/llm_preannotation_report.json
annotation/llm_gold_raw_responses.jsonl
```

LLM outputs are candidate preannotations only. They must be reviewed and adjudicated by humans before becoming gold data.

The no-argument LLM command is a one-event smoke run so API failures are auditable without blocking the workflow. Use `python scripts/run_llm_gold_preannotation.py --all-events` for the full formal pass.

## Step 6: Gold Data

Only after evidence has been normalized and annotated, create:

```text
gold_tuples.jsonl
gold_event_chains.jsonl
```

Every gold record must cite `evidence_ids` that exist in `evidence.jsonl`.

Convert final human-reviewed sheets:

```bash
python scripts/convert_review_sheets_to_gold.py
python scripts/validate_gold_dataset.py
python scripts/inspect_gold_samples.py --num-events 3 --seed 42
```

Gold tuple `support_label` must be one of:

- `supported`
- `partially_supported`
- `unsupported`
- `insufficient_evidence`
