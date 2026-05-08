# PubEvent-SOA Annotation Guideline

This sheet is for human annotation only. It must not be treated as gold data until annotators review and complete the required fields.

## Task

For each evidence row, decide whether the text supports an evidence-grounded stakeholder opinion attribution tuple:

`<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>`

## Fields To Annotate

- `is_relevant`: mark whether this evidence is relevant to the event and usable for stakeholder opinion attribution.
- `annotated_stakeholder`: the actor whose opinion, stance, concern, response, or action is expressed. Examples: residents, property owners, government departments, enterprises, developers, platforms, media, experts.
- `annotated_opinion`: the concrete opinion, demand, concern, response, explanation, action, or position expressed by the stakeholder.
- `annotated_sentiment`: use `positive`, `negative`, `neutral`, `mixed`, or `unknown`.
- `annotated_rationale`: the short evidence-grounded reason for the annotation. Quote or summarize the part of the evidence that supports the tuple.
- `support_label`: choose one of `supported`, `partially_supported`, `unsupported`, `irrelevant`.
- `event_chain_step`: choose one of `trigger`, `diffusion`, `conflict`, `response`, `resolution`, `follow_up`.
- `event_chain_order`: integer order of this evidence in the event chain when applicable.
- `notes`: optional annotation comments, uncertainty, duplicate notes, or exclusion reasons.

## Concepts

Stakeholder means the public actor that holds or expresses the opinion or action. Do not use a vague stakeholder if the text clearly names a more specific actor.

Opinion means the stakeholder's claim, attitude, concern, demand, explanation, response, or action regarding the event.

Sentiment describes the polarity or stance of the opinion. Use `neutral` for factual official notices or procedural updates without clear support or opposition.

Rationale is the evidence-grounded justification for your label. It should be traceable to the text in the same row.

Support label describes how well this evidence supports the annotated tuple:

- `supported`: the row clearly supports the stakeholder, opinion, sentiment, and rationale.
- `partially_supported`: the row supports part of the tuple but lacks some detail.
- `unsupported`: the row is related but does not support the proposed tuple.
- `irrelevant`: the row is not useful for this event or stakeholder opinion task.

Event chain step describes the role of the evidence in the event development:

- `trigger`: initial cause or announcement.
- `diffusion`: wider reporting, sharing, or spread.
- `conflict`: explicit dispute, complaint, disagreement, or controversy.
- `response`: official, organizational, or stakeholder response.
- `resolution`: handling result, correction, settlement, or decision.
- `follow_up`: later update, monitoring, secondary discussion, or longer-term effect.

## Irrelevant Evidence

Mark evidence as `irrelevant` when it is unrelated to the configured event, only explains a general policy, is a generic SEO article, lacks a concrete event or stakeholder, is duplicated without new information, or contains no usable stakeholder opinion/action.

## Special Cases

Official responses should usually be annotated as `政府部门` or the specific agency if they directly respond, announce, explain, investigate, or report handling results.

Media reports should be annotated for the stakeholder opinion they report. If the article only summarizes facts without a stakeholder view, mark the stakeholder as media only when the media itself makes an evaluative claim.

Generic policy explanations should usually be `irrelevant` unless they directly describe the event, affected stakeholders, or an official handling result.

Duplicate reports may be marked relevant only when they add a distinct stakeholder, source, timeline step, or detail. Otherwise mark them as duplicate in `notes`.
