# PubEvent-SOA Gold Tuple Expansion

Read the event, evidence pack, and existing tuples. The event currently has {{CURRENT_TUPLE_COUNT}} tuples but needs at least {{TARGET_MIN_TUPLE_COUNT}}. Propose at most {{TUPLES_NEEDED}} additional candidate gold stakeholder-opinion tuples that are DISTINCT from the existing ones below.

Return JSON only:

```json
{
  "event_id": "EVENT_ID",
  "tuples": [
    {
      "stakeholder": "specific stakeholder NOT already in existing tuples",
      "opinion": "evidence-grounded opinion, demand, response, action, or concern - distinct from existing opinions",
      "sentiment": "positive|negative|neutral|mixed|unknown",
      "rationale": "short justification grounded in cited evidence",
      "evidence_ids": ["ev-00001"],
      "support_label": "supported|partially_supported|unsupported|unclear"
    }
  ]
}
```

Rules:

- Use only evidence IDs present in the input.
- Every tuple must cite at least one evidence ID.
- Avoid duplicating stakeholders and opinions already present in EXISTING_TUPLES.
- Prioritize stakeholder groups and source types not yet covered by existing tuples.
- Do not use `irrelevant` as a tuple support label.
- Return an empty `tuples` list if no additional tuple can be grounded.
- Prefer fewer, better-grounded tuples over exhaustive coverage.

## Existing Tuples (DO NOT duplicate these stakeholders or opinions)

{{EXISTING_TUPLES_JSON}}

## Event Context

{{EVENT_CONTEXT_JSON}}
