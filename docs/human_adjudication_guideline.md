# Human Adjudication Guideline

This guideline defines how to upgrade `silver_v1` records into `human_gold_v1`.

## Silver vs Human Gold

`silver_v1` is copied from LLM preannotation. It is useful as reviewer input, but it is not final gold.

`human_gold_v1` is produced only after human adjudication. A record enters `human_gold_v1` only when a reviewer makes an explicit decision and the conversion/audit scripts validate the result.

Original `llm_gold_*` and canonical evidence files must not be modified during this process.

## Tuple Review Standard

A tuple is valid only when all of these are true:

- `stakeholder` names a concrete actor or actor group grounded in evidence.
- `opinion` states an atomic, evidence-supported position, complaint, response, action stance, or governance claim.
- `sentiment` follows the project label set: `positive`, `negative`, `neutral`, or `mixed`.
- `rationale` explains the support without adding facts not present in evidence.
- `evidence_ids` are nonempty and point to records that directly support the tuple.

Prefer concise, normalized stakeholder names. Avoid vague actors such as "公众" or "有关部门" unless the evidence itself only supports that level of specificity.

## Chain Review Standard

A chain should describe the event evolution using evidence-grounded stages or steps. It should not be a generic background summary.

Valid chains should:

- Use only evidence-supported nodes.
- Preserve temporal or causal order where evidence supports it.
- Reference evidence from the same `event_id`.
- Avoid duplicating near-identical chains unless they represent distinct stakeholder or stage coverage.

## Review Decisions

`accept`: The silver record is correct and can enter `human_gold_v1` unchanged.

`revise`: The record is mostly useful but must be corrected. Fill the relevant `revised_*` fields. The converter uses `revised_*` values, not original values.

`drop`: The record is wrong, unsupported, duplicate, too vague, or not useful. It will not enter `human_gold_v1`.

`add_missing`: Add a missing tuple or chain. Required fields and `evidence_ids` must be filled. Added records must be evidence-grounded.

`uncertain`: Reviewer cannot decide confidently. This is the default pre-review value and never enters `human_gold_v1`.

## Evidence Support

Evidence support is strong when the evidence explicitly contains the stakeholder and the opinion/action/stance, or clearly supports them through a direct factual statement.

Evidence is weak when it only provides generic event background, policy context, media framing, or a loosely related incident.

Do not accept a tuple if the evidence supports only the event but not the stakeholder-opinion relation.

## Sentiment

Use `negative` for criticism, complaints, opposition, dissatisfaction, risk concern, or harm claims.

Use `positive` only for explicit approval, support, satisfaction, praise, or welcome.

Use `neutral` for factual announcements, official process updates, investigation results, policy explanations, or administrative actions without clear approval/disapproval.

Use `mixed` only when the same stakeholder has clearly mixed positive and negative signals in the cited evidence.

## Rationale Over-Inference

Reject or revise a rationale when it:

- Adds motives or causal claims not present in evidence.
- Treats generic background as stakeholder opinion.
- Converts an official action into positive sentiment without explicit approval.
- Infers public attitude from media reporting alone.
- Combines multiple unsupported claims into one tuple.

## Tuple-Chain Consistency

Tuple evidence should overlap with the event chain evidence for the same event whenever possible.

If a tuple references a specific `chain_id`, that chain must exist in `human_gold_event_chains_v1.jsonl`.

If tuple evidence has no overlap with any same-event chain evidence, keep the tuple only when the evidence independently supports it and note the reason in `reviewer_note`.

## Uncertain Handling

`uncertain` is the default value before review. It is intentionally excluded from `human_gold_v1`.

Do not batch-replace `uncertain` with `accept`. Every accepted or revised row must reflect actual human review.
