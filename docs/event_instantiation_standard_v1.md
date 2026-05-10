# PubEvent-SOA Event Instantiation Standard v1

## Purpose

PubEvent-SOA gold annotation must be built on concrete public event instances, not broad issue templates. A concrete event instance is a uniquely identifiable public occurrence with a factual time window, location or institutional anchor, trigger, traceable public sources, and identifiable stakeholders.

## Three-Layer Data Flow

```text
topic_seeds.jsonl
  -> candidate_event_instances.jsonl
  -> events.jsonl
  -> raw/raw_posts.jsonl
  -> evidence.jsonl
  -> gold_tuples.jsonl / gold_event_chains.jsonl
```

### topic_seeds.jsonl

`topic_seeds.jsonl` stores topic-level discovery seeds. The current 50 legacy records were migrated from the old `events.jsonl` into this file. They preserve field coverage, seed keywords, stakeholder hints, stance hints, and discovery windows.

Topic seeds may contain placeholder wording such as "某市", "某地", "某校", "某医院", or "某平台". That is acceptable for discovery seeds and invalid for formal events.

Source scopes use `public_social`; the legacy `social_media` label is normalized during migration.

### candidate_event_instances.jsonl

`candidate_event_instances.jsonl` stores manually found candidate concrete events. Editors should use the candidate instance sheet to record:

- factual location
- factual time window
- trigger
- anchor entities
- traceable anchor URLs
- discovery queries
- screening decisions

Only `candidate_status=accepted` records can be promoted.

### events.jsonl

`events.jsonl` stores accepted concrete formal event instances only. A formal event must include:

- `event_id`
- `topic_id`
- `event_name`
- `event_description`
- `location`
- `time_window`
- `trigger`
- `anchor_entities`
- `anchor_urls`
- `source_scope`
- `queries`
- `selection_status`
- `instance_version`

Records with placeholder expressions, missing location, missing trigger, missing anchor URLs, missing `topic_id`, or non-factual time windows must be rejected by validation.

## Promotion Rule

`scripts/promote_candidate_events.py` reads `candidate_event_instances.jsonl` and promotes only accepted candidates that pass hard validation. It must not infer or fabricate real events from a topic seed.

## Gold Annotation Rule

Formal gold tuples and event chains can only be produced after:

1. accepted concrete events exist in `events.jsonl`
2. evidence has been collected and normalized for those events
3. human review and adjudication has completed

The earlier 10-event LLM/gold pilot was run against topic-level records. It is useful for prompt and workflow diagnosis only and must not be cited as a formal gold test set.

## Readiness States

`python scripts/validate_event_instantiation_data.py` reports:

- `topic_seed_valid`
- `candidate_instances_valid`
- `formal_events_valid`
- `formal_events_ready`

An empty `events.jsonl` is not a schema error for the instantiation layer, but `formal_events_ready=false` keeps evidence collection, gold construction, and paper experiments blocked.
