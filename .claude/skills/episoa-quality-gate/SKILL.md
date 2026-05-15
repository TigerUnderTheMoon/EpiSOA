---
name: episoa-quality-gate
description: Apply EpiSOA dataset quality gates for event evidence construction, source balance, deduplication, and annotation readiness.
---

# EpiSOA Quality Gate Skill

Use this skill when evaluating EpiSOA data construction quality.

## Target construction standard

For each event:

- raw collection layer: 50-60 evidence candidates
- clean evidence layer: 30-35 evidence items
- LLM annotation input layer: 20-25 evidence items
- final gold supporting evidence: 10-15 items

## Required quality gates

Check:

1. Evidence count per event
2. Unique URL deduplication
3. Duplicate `(event_id, url)` pairs
4. Source balance:
   - official
   - mainstream_news
   - local_news
   - public_web
   - social_media
   - forum
   - public_interaction
5. Official-source coverage
6. Interaction-class coverage where available
7. Whether low tuple/chain count is caused by insufficient evidence, poor source diversity, or weak event formulation
8. Whether recollection is needed
9. Whether the event is annotation-ready

## Response format

Use this structure:

1. Overall verdict: PASS / NEEDS REPAIR / BLOCKED
2. Event-level problem list
3. Root cause diagnosis
4. Repair plan
5. Exact command or JSONL plan needed next

## Project convention

Prefer using existing scripts in `scripts/` rather than creating new one-off scripts unless necessary.
