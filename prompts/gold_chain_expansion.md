# PubEvent-SOA Gold Event-Chain Expansion

Read the event, evidence pack, and existing chains. The event currently has {{CURRENT_CHAIN_COUNT}} chains but needs at least {{TARGET_MIN_CHAIN_COUNT}}. Propose at most {{CHAINS_NEEDED}} additional candidate event-chain summaries that are DISTINCT from the existing ones below.

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
- Avoid duplicating chain sequences already present in EXISTING_CHAINS.
- Generate chains from different perspective (e.g., official narrative vs public narrative) if possible.
- Return an empty `event_chains` list if no additional chain can be grounded.

## Existing Chains (DO NOT duplicate these sequences)

{{EXISTING_CHAINS_JSON}}

## Event Context

{{EVENT_CONTEXT_JSON}}
