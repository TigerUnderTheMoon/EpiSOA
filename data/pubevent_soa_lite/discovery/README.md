# PubEvent-SOA Discovery Corpus

This directory archives outputs produced before the topic-to-event instantiation refactor.

These files are topic-level discovery artifacts. They were generated from the legacy 50 topic seeds, not from accepted concrete formal event instances.

## Contents

- `topic_raw_posts.jsonl`: legacy topic-level raw posts copied from `raw/raw_posts.jsonl`
- `topic_evidence.jsonl`: legacy topic-level normalized evidence copied from `evidence.jsonl`
- `topic_evidence_filtered.jsonl`: legacy filtered topic evidence, if present
- `topic_evidence_merged.jsonl`: legacy merged topic evidence, if present
- `topic_annotation/`: legacy evidence-level annotation sheet and summary
- `topic_pilot/`: legacy LLM/gold pilot outputs and audit material

## Allowed Use

Use this corpus only for:

- topic-to-event discovery
- concrete event candidate discovery
- diagnostic analysis of prompts, annotation sheets, and collection coverage

## Not Allowed

Do not use this directory as formal paper data.

Do not use these files for:

- formal `events.jsonl`
- formal `evidence.jsonl`
- formal `gold_tuples.jsonl`
- formal `gold_event_chains.jsonl`
- paper experiments

Formal paper data must start from accepted concrete events in `../events.jsonl`.
