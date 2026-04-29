# PubEvent-SOA Formal Dataset Schema

This document defines the required JSONL schemas for `data/pubevent_soa_formal/`.
Each file must contain one JSON object per line. Empty files are allowed during
data preparation, but formal experiments are blocked until all four files are
non-empty and pass validation.

## `events.jsonl`

| Field | Type | Required | Example | Validation |
| --- | --- | --- | --- | --- |
| `event_id` | string | yes | `"evt-urban-001"` | Non-empty and unique. |
| `target_event` | string | yes | `"Public hearing on Riverside renewal plan"` | Non-empty public event description. |
| `time_window` | object | no | `{"start":"2026-01-01","end":"2026-01-31"}` | If present, use ISO-like date or datetime strings. |
| `event_chain` | array of strings | yes | `["Plan announced","Public hearing"]` | Non-empty; all items non-empty strings. |
| `title` | string | no | `"Riverside renewal hearing"` | Optional display title. |
| `source` | string | no | `"Municipal notice"` | Optional provenance note. |
| `notes` | string | no | `"Curated by annotator A"` | Optional curation note. |

Example:

```json
{"event_id":"evt-urban-001","target_event":"Public hearing on Riverside renewal plan","time_window":{"start":"2026-01-01","end":"2026-01-31"},"event_chain":["Plan announced","Public hearing"],"title":"Riverside renewal hearing","source":"Municipal notice","notes":"Human-curated formal event."}
```

## `evidence.jsonl`

| Field | Type | Required | Example | Validation |
| --- | --- | --- | --- | --- |
| `evidence_id` | string | yes | `"ev-urban-001"` | Non-empty and unique. |
| `event_id` | string | yes | `"evt-urban-001"` | Must exist in `events.jsonl`. |
| `platform` | string | yes | `"City Gazette"` | Non-empty source or platform name. |
| `url` | string URL | yes | `"https://example-news.invalid/item"` | Must be an absolute URL when available. Do not use mock/example sources in formal data. |
| `timestamp` | string datetime | yes | `"2026-01-10T09:00:00Z"` | ISO-8601 datetime preferred. |
| `text` | string | yes | `"Residents opposed the relocation timeline."` | Non-empty evidence text; no direct personal identifiers. |
| `author_alias` | string or null | no | `"Residents committee"` | Public organization, stakeholder alias, or anonymized alias. |
| `source_type` | string | yes | `"news"` | One of `news`, `social_media`, `official`, `blog`, `forum`, `other`. |
| `metadata` | object | no | `{"stakeholder":"Residents","sentiment":"negative"}` | Optional structured curation fields. |

Example:

```json
{"evidence_id":"ev-urban-001","event_id":"evt-urban-001","platform":"City Gazette","url":"https://public-source.invalid/riverside-hearing","timestamp":"2026-01-10T09:00:00Z","text":"Residents opposed the relocation timeline during the public hearing.","author_alias":"Residents committee","source_type":"news","metadata":{"stakeholder":"Residents","opinion":"The relocation timeline is too rushed.","sentiment":"negative","rationale":"The evidence directly reports residents' objection."}}
```

## `gold_tuples.jsonl`

| Field | Type | Required | Example | Validation |
| --- | --- | --- | --- | --- |
| `tuple_id` | string | no | `"tuple-00001"` | Optional stable tuple ID. |
| `event_id` | string | yes | `"evt-urban-001"` | Must exist in `events.jsonl`. |
| `event` | string | yes | `"Public hearing on Riverside renewal plan"` | Non-empty event text. |
| `stakeholder` | string | yes | `"Residents"` | Non-empty stakeholder. |
| `opinion` | string | yes | `"The timeline is too rushed."` | Non-empty opinion. |
| `sentiment` | string | yes | `"negative"` | One of `positive`, `negative`, `neutral`, `mixed`, `unknown`. |
| `rationale` | string | yes | `"Evidence reports residents' objection."` | Non-empty rationale. |
| `event_chain` | array of strings | yes | `["Plan announced","Public hearing"]` | Non-empty; all items non-empty strings. |
| `evidence_ids` | array of strings | yes | `["ev-urban-001"]` | Non-empty; every ID must exist in `evidence.jsonl`. |
| `support_label` | string | yes | `"supported"` | One of `supported`, `partially_supported`, `unsupported`. |
| `support_score` | number | yes | `0.9` | Number in `[0, 1]`. |
| `verified` | boolean | yes | `true` | Must be boolean. |
| `label_source` | string | no | `"human_gold"` | Must not be `llm_silver` in gold data. |
| `notes` | string | no | `"Adjudicated by lead annotator"` | Optional annotation note. |

Example:

```json
{"tuple_id":"tuple-00001","event_id":"evt-urban-001","event":"Public hearing on Riverside renewal plan","stakeholder":"Residents","opinion":"The relocation timeline is too rushed.","sentiment":"negative","rationale":"Evidence reports residents' objection.","event_chain":["Plan announced","Public hearing"],"evidence_ids":["ev-urban-001"],"support_label":"supported","support_score":0.9,"verified":true,"label_source":"human_gold","notes":"Human annotation."}
```

## `gold_event_chains.jsonl`

| Field | Type | Required | Example | Validation |
| --- | --- | --- | --- | --- |
| `event_id` | string | yes | `"evt-urban-001"` | Must exist in `events.jsonl`. |
| `event_chain` | array of strings | yes | `["Plan announced","Public hearing"]` | Non-empty; all items non-empty strings. |
| `chain_type` | string | no | `"temporal"` | Optional label such as `temporal`, `causal`, or `mixed`. |
| `evidence_ids` | array of strings | no | `["ev-urban-001"]` | If present, IDs should exist in `evidence.jsonl`. |
| `notes` | string | no | `"Gold chain for path recall"` | Optional annotation note. |

Example:

```json
{"event_id":"evt-urban-001","event_chain":["Plan announced","Public hearing"],"chain_type":"temporal","evidence_ids":["ev-urban-001"],"notes":"Human-curated gold event chain."}
```

## Formal Validation Rules

- Formal files must not contain `mock`, `example.org`, or `fictional`.
- Formal files must be non-empty before real experiments.
- `gold_tuples.event_id` must exist in `events.jsonl`.
- `gold_tuples.evidence_ids` must exist in `evidence.jsonl`.
- `gold_event_chains.event_id` must exist in `events.jsonl`.
- Direct personal identifiers such as emails or phone numbers are rejected in evidence.
- Real experiments remain blocked until `outputs/dataset_validation_formal.json` has `is_formal_dataset=true`.
