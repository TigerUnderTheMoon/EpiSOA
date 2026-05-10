# PubEvent-SOA Gold Event-Chain Preannotation

Read the event and evidence pack. Propose at most 3 candidate event-chain summaries for human review.

Return JSON only:

```json
{
  "event_id": "EVENT_ID",
  "event_chains": [
    {
      "event_chain": [
        "trigger or background",
        "conflict or stakeholder reaction",
        "official or organizational response",
        "resolution or follow-up"
      ],
      "evidence_ids": ["ev-00001"]
    }
  ]
}
```

Rules:

- Use only evidence IDs present in the input.
- Every chain must cite at least one evidence ID.
- Prefer concise chronological nodes.
- Return an empty `event_chains` list if no chain can be grounded.

Input:

{{EVENT_CONTEXT_JSON}}
