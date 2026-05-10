# PubEvent-SOA Gold Tuple Preannotation

Read the event and evidence pack. Propose at most 5 high-confidence candidate gold stakeholder-opinion tuples that should be reviewed by humans.

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
- Every tuple must cite at least one evidence ID.
- Do not use `irrelevant` as a tuple support label.
- Return an empty `tuples` list if no tuple is sufficiently grounded.
- You may identify tuples missing from existing system predictions.
- Prefer fewer, better-grounded tuples over exhaustive coverage.

Input:

{{EVENT_CONTEXT_JSON}}
