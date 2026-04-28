# PubEvent SOA Formal Dataset

This directory is reserved for human-curated formal paper data. Do not put placeholder, synthetic, or demonstration records into `events.jsonl`, `evidence.jsonl`, `gold_tuples.jsonl`, or `gold_event_chains.jsonl`.

## Current State

`events.jsonl` and `evidence.jsonl` are currently empty. The template files in this directory are documentation aids only:

- `events_template.jsonl`
- `evidence_template.jsonl`

Do not pass the template files to experiment scripts.

## Fill `events.jsonl`

Write one JSON object per line. Each event should have:

- `event_id`: stable unique ID, such as an internal curation ID.
- `target_event`: public event description used by the pipeline.
- `time_window`: object with `start` and `end` timestamps when available.
- `event_chain`: non-empty list of event nodes for chain-level evaluation.

Optional useful fields include `title`, `source`, and `notes`.

## Fill `evidence.jsonl`

Write one JSON object per line. Each evidence record should have:

- `evidence_id`: stable unique ID.
- `event_id`: must match an `event_id` in `events.jsonl`.
- `platform`: source platform or publication name.
- `url`: original evidence URL when available.
- `timestamp`: ISO-8601 timestamp.
- `text`: evidence text used for attribution.
- `author_alias`: author, organization, or stakeholder alias when available.
- `source_type`: source category, such as `news`, `social_media`, `official`, `forum`, `report`, or `other`.
- `metadata`: optional object for `stakeholder`, `sentiment`, `opinion`, language, country, curation notes, and provenance.

## Generate `annotation_sheet_formal.csv`

After `events.jsonl` and `evidence.jsonl` contain real curated records, run:

```powershell
python scripts/build_annotation_sheet.py `
  --events data/pubevent_soa_formal/events.jsonl `
  --evidence data/pubevent_soa_formal/evidence.jsonl `
  --output outputs/annotation_sheet_formal.csv
```

If the input files are empty, this creates a header-only CSV.

## Fill `annotation_sheet_formal_filled.csv`

Annotators should copy or export `outputs/annotation_sheet_formal.csv` to:

```text
outputs/annotation_sheet_formal_filled.csv
```

Fill these annotation columns:

- `annotated_stakeholder`
- `annotated_opinion`
- `annotated_sentiment`
- `annotated_rationale`
- `annotated_event_chain`
- `annotated_evidence_ids`
- `support_score`
- `verified`
- `notes`

Use semicolons in `annotated_event_chain` and `annotated_evidence_ids` when a cell contains multiple items.

## Convert `gold_tuples.jsonl`

After human annotation is complete, run:

```powershell
python scripts/convert_annotation_csv_to_gold.py `
  --input outputs/annotation_sheet_formal_filled.csv `
  --output data/pubevent_soa_formal/gold_tuples.jsonl `
  --validation-output outputs/dataset_validation_formal.json
```

This conversion skips rows without human-filled attribution fields. It should not be used to invent missing gold tuples.

## Validate The Dataset

Run validation before any formal experiment:

```powershell
python scripts/validate_dataset.py `
  --events data/pubevent_soa_formal/events.jsonl `
  --evidence data/pubevent_soa_formal/evidence.jsonl `
  --gold-tuples data/pubevent_soa_formal/gold_tuples.jsonl `
  --gold-event-chains data/pubevent_soa_formal/gold_event_chains.jsonl `
  --output outputs/dataset_validation_formal.json
```

Formal experiments should proceed only when the validation report has `is_formal_dataset` set to `true`.
