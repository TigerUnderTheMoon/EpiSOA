# Oracle Evidence Report

## Setup
- Setting: `full_oracle_evidence`.
- Gold tuple text is not provided to the model; only gold evidence IDs are forced into the prompt.
- Non-gold evidence fills remaining slots using the normal selection strategy.

## Results
- P0 full Tuple-F1-soft: 0.386
- full_oracle_evidence Tuple-F1-soft: 0.4430
- Delta: 0.057
- full_oracle_evidence Precision: 0.5714
- full_oracle_evidence Recall: 0.3617
- full_oracle_evidence Num-Tuples: 119.0000
- Events with truncated/missing oracle gold evidence: {}

## Interpretation
- Oracle evidence improves over P0 full, so evidence selection contributes, but extraction/gold/metric issues remain.

## Coverage Check
- Events with gold tuples: 50
- Raw oracle response records: 50
