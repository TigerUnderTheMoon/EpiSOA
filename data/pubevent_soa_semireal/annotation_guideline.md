# PubEvent-SOA Semi-real Annotation Guideline

Annotate one public event at a time. The task is stakeholder-opinion attribution, not broad monitoring.

## Privacy and Source Rules

- Use only public pages that can be accessed without login or technical bypass.
- Store short evidence snippets, not full pages.
- Do not save raw author names in clean evidence. Use `author_alias`.
- Do not save phone numbers, email addresses, ID numbers, private addresses, or user homepage/profile URLs.
- Keep the public source URL, platform, timestamp, source type, and traceability metadata.

## Files

- `events.jsonl`: event packages with `event_id`, `target_event`, `event_chain`, `stakeholders`, `time_window`, and `metadata`.
- `evidence_raw.jsonl`: raw public-web snippets before privacy filtering. This file may contain fields such as `author_name` or `author_profile_url` only for local cleaning tests.
- `evidence_clean.jsonl`: anonymized evidence aligned with `EvidenceRecord`. Event IDs should be stored in `metadata.event_id`.
- `gold_tuples.jsonl`: attribution tuples aligned with `AttributionTuple`.
- `gold_event_chains.jsonl`: event-chain evidence packages.
- `sources.md`: source collection notes and constraints.

## Stakeholder

Use public actor or group labels: `residents`, `city engineers`, `small businesses`, `transit agency`, `rider groups`. Avoid private personal names.

## Opinion

Write the concrete opinion, request, concern, support, or objection expressed by the stakeholder. It must be verifiable from evidence.

## Sentiment

Use `positive`, `negative`, `neutral`, `mixed`, or `unknown`.

## Rationale

Explain how the evidence and event chain support the tuple. Do not infer motives beyond the snippet.

## Evidence

Cite evidence objects compatible with `EvidenceRecord`: `evidence_id`, `platform`, `url`, `timestamp`, `text`, `author_alias`, `source_type`, and `metadata`.

## Event Chain

Use an ordered list of event phrases and relation labels such as `precedes`, `triggers`, `responds_to`, `amplifies`, or `caused_by`.
