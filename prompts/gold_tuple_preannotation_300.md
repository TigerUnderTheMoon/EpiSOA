# PubEvent-SOA 300-Tuple Preannotation Pass

Read the event and evidence pack. Propose exactly 6 candidate stakeholder-opinion tuples for human review whenever the evidence supports 6 distinct candidates. Across 50 events this targets 300 tuple candidates.

Return JSON only:

```json
{
  "event_id": "EVENT_ID",
  "tuples": [
    {
      "stakeholder": "specific stakeholder",
      "opinion": "evidence-grounded opinion, demand, response, action, or concern",
      "sentiment": "positive|negative|neutral|mixed|unknown",
      "rationale": "short justification grounded in cited evidence",
      "evidence_ids": ["ev-00001"],
      "support_label": "supported|partially_supported|unsupported|insufficient_evidence"
    }
  ]
}
```

Rules:

- Use only evidence IDs present in the input.
- Return exactly 6 tuples if six distinct evidence-grounded stakeholder-opinion candidates can be identified.
- If fewer than 6 candidates are grounded, return the maximum grounded number and do not invent facts.
- Prefer stakeholder diversity: include official actors, affected residents/users, enterprises/platforms, experts, media, or public groups when evidence supports them.
- Prefer evidence diversity: use at least 2 evidence IDs for a tuple when available.
- Use `partially_supported` for plausible but incomplete support; use `insufficient_evidence` only when a candidate should be routed to human review because evidence is weak.
- Do not use `irrelevant` as a support label.
- Keep each opinion atomic; do not merge multiple stakeholder positions into one tuple.
- These are silver candidates for human review, not final gold.

Input:

{{EVENT_CONTEXT_JSON}}
