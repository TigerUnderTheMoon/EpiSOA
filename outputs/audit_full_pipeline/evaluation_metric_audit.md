# Evaluation Metric Audit

## Code Findings
- `soft_tuple_f1` requires identical `event_id` before any match is considered.
- Matching is greedy one-to-one over candidate pairs sorted by score.
- Stakeholder and opinion are scored by character-level Jaccard; rationale and evidence support are not part of core F1.
- Sentiment accuracy is computed only over matched tuples.

## Diagnosis
- Baseline char-Jaccard threshold 0.5 result: {'metric': 'char_jaccard', 'threshold': 0.5, 'Tuple-F1': 0.386, 'Precision': 0.567, 'Recall': 0.2926, 'Sentiment-Acc': 0.7091, 'Stakeholder-Recall': 0.3191}
- Lowering char-Jaccard threshold to 0.3 result: {'metric': 'char_jaccard', 'threshold': 0.3, 'Tuple-F1': 0.4702, 'Precision': 0.6907, 'Recall': 0.3564, 'Sentiment-Acc': 0.7015, 'Stakeholder-Recall': 0.3511}
- If F1 rises sharply at lower thresholds, expression mismatch is a contributor. If it remains low, recall/extraction/evidence coverage dominate.
- Chinese short text can be underestimated by raw character Jaccard when synonyms or normalized stakeholder names differ.

## Recommendation
- Report a multi-metric table: Strict-F1, Soft-F1, Stakeholder-F1/Recall, Opinion-F1, Evidence-grounded Precision, Recall@K/Coverage.
- Keep Tuple-F1-soft but do not use it as the only headline metric.
- Add a no-API semantic-similarity placeholder only as future work; do not silently call an embedding/LLM service during evaluation.
