# PubEvent-SOA-lite Annotation Guideline

PubEvent-SOA-lite is a small template dataset for public-event stakeholder-opinion attribution. Use public, fictional, or non-sensitive information only. Do not include real private names, phone numbers, emails, ID numbers, home addresses, or user profile URLs.

## File Formats

`events.jsonl` contains one event package per line. Each row should include `event_id`, `target_event`, `event_chain`, `stakeholders`, `time_window`, and `metadata`.

`evidence.jsonl` contains normalized public evidence. Each row must include `evidence_id`, `event_id`, `platform`, `url`, `timestamp`, `text`, `author_alias`, `source_type`, and `metadata`.

`gold_tuples.jsonl` contains gold attribution tuples aligned with `AttributionTuple`. Each row must include `event`, `stakeholder`, `opinion`, `sentiment`, `rationale`, `event_chain`, `evidence`, `support_score`, and `verified`.

`gold_event_chains.jsonl` contains gold event-chain packages. Each row must include `target_event`, `event_chain`, `relation_types`, `stakeholders`, `candidate_rationales`, and `evidence`.

## Stakeholder

Annotate the public actor, institution, organization, affected group, or community that expresses or holds the opinion. Prefer group-level labels such as `rider groups`, `transit agency`, or `neighborhood businesses`. Do not use private personal names.

## Opinion

Annotate the stakeholder's concrete stance, concern, request, support, objection, or interpretation. Keep the opinion concise and verifiable against cited evidence.

## Sentiment

Use one of `positive`, `negative`, `neutral`, `mixed`, or `unknown`.

- `positive`: supportive or approving.
- `negative`: opposing, critical, worried, or dissatisfied.
- `neutral`: procedural, descriptive, or balanced.
- `mixed`: contains both support and concern.
- `unknown`: evidence does not clearly reveal sentiment.

## Rationale

Write a short explanation connecting the stakeholder, opinion, sentiment, event chain, and cited evidence. Do not invent causal claims beyond what the evidence supports.

## Evidence

The `evidence` field in gold files should contain evidence objects compatible with `EvidenceRecord`: `evidence_id`, `platform`, `url`, `timestamp`, `text`, `author_alias`, `source_type`, and `metadata`.

Use `author_alias` only. Do not store raw author names. Keep source URLs for evidence pages, but do not store user homepage/profile URLs.

## Event Chain

Annotate `event_chain` as an ordered list of short event phrases. Use `relation_types` to describe transitions between adjacent events. Allowed relation labels should match the project graph vocabulary where possible, such as `precedes`, `triggers`, `responds_to`, `amplifies`, or `caused_by`.

## Quality Checks

- Every `evidence_id` referenced in gold files should exist in `evidence.jsonl`.
- Every `event_id` in `evidence.jsonl` should exist in `events.jsonl`.
- Every tuple must have non-empty `evidence`.
- Do not force attribution when evidence is insufficient.
