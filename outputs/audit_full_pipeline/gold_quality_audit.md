# Gold Quality Audit

## Verdict
- Current experiment gold file should be labelled **silver/pseudo-gold, not strictly human-verified gold**.
- The configured file `data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl` has fields `event_id, candidate_id, source_type, stakeholder, opinion, sentiment, rationale, evidence_ids, support_label` and no explicit human verification fields.
- The reviewed export exists, but reviewer/annotator distribution is `{'auto_reviewer': 188}` and all accepted rows are from `auto_reviewer`; this is not evidence of independent human review.

## Counts
- Events with gold tuples: 50
- Gold tuples: 188
- Gold chains: 138
- Tuple count per event: {'min': 3, 'median': 3.5, 'mean': 3.76, 'max': 5}
- Events <2 tuples: []
- Events >6 tuples: []

## Distributions
- support_label: {'supported': 170, 'partially_supported': 18}
- sentiment: {'mixed': 5, 'positive': 38, 'negative': 88, 'neutral': 57}
- gold evidence source_type: {'public_web': 45, 'mainstream_news': 122, 'official': 59, 'social_media': 113, 'public_interaction': 13, 'forum': 8}

## Required Answers
- Can it be called gold? No. It is LLM preannotation with an auto-reviewed export, so it should be called silver/pseudo-gold.
- Must human verification be done? Yes. At least one real human pass is mandatory; for paper-grade benchmark claims, use two annotators plus adjudication.
- Are 188 tuples enough? Not for a strong benchmark claim. It may support a pilot/diagnostic study, but not a convincing一区 benchmark.
- Suggested expansion: minimum 100 events and 300-500 human-adjudicated tuples; better 150-200 events and 600+ tuples.
- Naming: use silver benchmark / weakly supervised benchmark until real human verification is complete.
