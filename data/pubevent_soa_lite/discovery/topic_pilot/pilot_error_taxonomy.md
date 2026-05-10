# PubEvent-SOA Pilot Error Taxonomy

Use this taxonomy when reviewing `gold_pilot_audit_sheet.csv`. The goal is to identify recurring LLM preannotation errors before revising prompts or annotation guidelines.

## missing_tuple

Definition: The tuple request completed successfully, but the LLM proposed no gold-worthy stakeholder-opinion tuple for an event.

Typical example: Evidence includes residents opposing a relocation plan, but no tuple captures the residents' objection.

Human correction: Mark `human_judgment=missing_gold_tuple`, add the missing tuple in corrected fields, and cite evidence IDs.

Usual fix: Prompt if the omission is frequent across events; human review if rare or evidence is ambiguous.

Do not use `missing_tuple` when the tuple request failed because of API timeout, authentication, rate limiting, or another infrastructure problem. Those rows should have `tuple_generation_status=api_failure` and should be rerun before judging model quality.

## infrastructure_failure

Definition: The tuple or chain task did not complete because the LLM request failed before a parseable response was available.

Typical example: `llm_preannotation_audit.jsonl` records `request_status=failed` and `error_type=api_timeout`.

Human correction: Leave `human_judgment` blank until the task is rerun successfully. Do not count it as model omission.

Usual fix: Operational retry, smaller evidence pack, longer timeout, or API/provider configuration. This is not primarily a prompt or guideline issue.

## parse_failure

Definition: The request returned a response, but the response could not be parsed or validated as the expected structured JSON.

Typical example: The model returns prose instead of JSON, cites unknown evidence IDs, or omits required fields.

Human correction: Leave `human_judgment` blank until the task is rerun or manually inspected from the raw response.

Usual fix: Prompt if frequent; parser hardening only when the response is clearly recoverable without changing semantics.

## wrong_stakeholder

Definition: The tuple attributes an opinion or action to the wrong actor.

Typical example: A news article reports an official response, but the tuple labels the media outlet as the stakeholder.

Human correction: Fill `corrected_stakeholder` with the actor that actually holds or expresses the opinion.

Usual fix: Prompt and guideline, especially for media paraphrase and official response cases.

## wrong_opinion_boundary

Definition: The opinion is too broad, too narrow, combines multiple opinions, or includes background facts not held by the stakeholder.

Typical example: A tuple merges resident compensation complaints and developer funding problems into one opinion.

Human correction: Rewrite `corrected_opinion` as one evidence-grounded claim, demand, concern, response, or action.

Usual fix: Prompt if the model often over-merges; guideline if reviewers disagree on boundary rules.

## wrong_sentiment

Definition: Sentiment does not match the stakeholder stance.

Typical example: A procedural official notice is labeled negative instead of neutral.

Human correction: Set `corrected_sentiment` to `positive`, `negative`, `neutral`, `mixed`, or `unknown`.

Usual fix: Guideline for borderline sentiment definitions; prompt if errors are systematic.

## unsupported_rationale

Definition: The rationale is not supported by the cited evidence, adds external inference, or overstates what the evidence says.

Typical example: Evidence says an agency opened an investigation, but rationale claims the dispute was resolved.

Human correction: Rewrite `corrected_rationale` using only cited evidence text, or mark the tuple wrong.

Usual fix: Prompt for stricter evidence grounding; human review remains necessary.

## wrong_evidence_ids

Definition: The cited evidence IDs are missing, irrelevant, from another event, or do not support the tuple.

Typical example: A resident complaint tuple cites a generic policy explainer instead of the complaint report.

Human correction: Fill `corrected_evidence_ids` with supporting IDs from `evidence.jsonl`.

Usual fix: Prompt if the model cites weak evidence; guideline if evidence sufficiency boundaries are unclear.

## duplicate_tuple

Definition: Two or more LLM tuples express the same stakeholder-opinion unit with no meaningful difference.

Typical example: Two resident dissatisfaction tuples differ only in wording but cite the same evidence.

Human correction: Keep one tuple, mark duplicates as duplicate, and note any merged evidence IDs.

Usual fix: Prompt for de-duplication; human review for final merge decisions.

## wrong_chain_order

Definition: The event-chain candidate orders stages incorrectly or mixes unrelated developments.

Typical example: Official response appears before the triggering complaint despite evidence chronology.

Human correction: Note the correct order in `notes` or the chain review sheet.

Usual fix: Prompt if chronological errors are frequent; guideline if stage definitions need clarification.

## media_attribution_error

Definition: The LLM attributes reported stakeholder views to media, or treats media summary as a stakeholder opinion without an evaluative claim.

Typical example: A news report quotes residents' opposition, but the tuple stakeholder is "media".

Human correction: Attribute the tuple to the quoted or paraphrased stakeholder.

Usual fix: Prompt and guideline.

## official_response_error

Definition: The LLM mishandles official responses, such as treating neutral procedural notices as opposition or failing to name the responsible agency.

Typical example: A housing bureau investigation notice is labeled as a resident complaint.

Human correction: Use the specific agency as stakeholder when available, and set sentiment according to the response stance.

Usual fix: Prompt and guideline.
