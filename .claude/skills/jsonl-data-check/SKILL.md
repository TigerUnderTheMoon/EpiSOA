---
name: jsonl-data-check
description: Check JSONL datasets for valid JSON, event counts, duplicate IDs, duplicate URLs, missing fields, source distribution, and low-coverage events.
---

# JSONL Data Check Skill

Use this skill for checking `.jsonl` files such as events, raw evidence, clean evidence, annotation input, and gold evidence.

## Standard checks

When the user asks to check a JSONL file, inspect or write a Python one-liner/script that reports:

1. total rows
2. valid JSON line count
3. invalid JSON line numbers
4. event_id distribution
5. missing event_id or key fields
6. duplicate raw IDs if applicable
7. duplicate `(event_id, url)` pairs if URL exists
8. source_type/source distribution if available
9. low-coverage events under the target threshold
10. min/max/average evidence count per event

## Output style

Return:
- concise summary table
- low-coverage event list
- suspected causes
- exact next command to fix or inspect

## Safety

Never modify the dataset during checking unless explicitly asked. Prefer writing check reports to `outputs/checks/`.
