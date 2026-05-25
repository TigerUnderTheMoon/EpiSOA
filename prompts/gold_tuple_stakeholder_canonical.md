# PubEvent-SOA Stakeholder-Canonical Tuple Preannotation

Read the event and all evidence rows. Identify event-level distinct stakeholder clusters first, then emit canonical stakeholder-opinion tuples for human review.

Return JSON only:

```json
{
  "event_id": "EVENT_ID",
  "tuples": [
    {
      "stakeholder_cluster_id": "SC_EVENT_ID_001",
      "stakeholder": "canonical stakeholder name",
      "stakeholder_aliases": ["alias 1", "alias 2"],
      "opinion": "evidence-grounded opinion, demand, response, action, or concern",
      "sentiment": "positive|negative|neutral|mixed|unknown",
      "rationale": "short justification grounded in cited evidence",
      "evidence_ids": ["ev-00001", "ev-00002"],
      "support_label": "supported|partially_supported|unsupported|insufficient_evidence",
      "canonical_tuple": true,
      "opinion_split_reason": ""
    }
  ]
}
```

Rules:

- Use only evidence IDs present in the input.
- First cluster aliases that refer to the same stakeholder. For example, "居民", "村民", and a named village resident group should be one stakeholder cluster when the evidence describes the same actor.
- Emit one canonical tuple per stakeholder cluster by default.
- When multiple evidence rows support the same stakeholder and the same opinion/action, merge their evidence IDs into the same tuple.
- Emit multiple tuples for the same `stakeholder_cluster_id` only when the same stakeholder has semantically different opinions, actions, demands, or responses.
- Every repeated `stakeholder_cluster_id` must have a non-empty `opinion_split_reason` explaining why this is a separate tuple.
- Do not invent stakeholders or opinions to reach a target count. Return the grounded number of canonical tuples.
- Prefer specific stakeholder names over broad categories when evidence supports them.
- Keep each opinion atomic and evidence-grounded.
- Use `partially_supported` for incomplete support and `insufficient_evidence` only when the candidate should be routed to human review because evidence is weak.
- Do not use `unclear`, `irrelevant`, or labels outside the JSON schema.
- These are silver candidates for human review, not final gold.

Input:

{{EVENT_CONTEXT_JSON}}
