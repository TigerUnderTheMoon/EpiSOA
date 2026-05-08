# PubEvent-SOA Lite Data Directory

This directory follows the five-stage paper data flow.

## Step 1: Event Selection

Human editors fill:

```text
events.jsonl
```

Each event is a query configuration, not evidence. It should contain at least `event_id` and `event_name` or `event_description`.

## Step 2: Evidence Collection

Run:

```bash
python scripts/collect_evidence.py
```

Input:

```text
events.jsonl
```

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

## Step 4: Annotation Sheet

Run:

```bash
python scripts/make_annotation_sheet.py
```

Output:

```text
annotation/annotation_sheet.csv
```

Annotators fill stakeholder, opinion, sentiment, rationale, event chain, evidence IDs, and support label.

## Step 5: Gold Data

Only after evidence has been normalized and annotated, create:

```text
gold_tuples.jsonl
gold_event_chains.jsonl
```

Every gold record must cite `evidence_ids` that exist in `evidence.jsonl`.
