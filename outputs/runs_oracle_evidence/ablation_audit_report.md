# Ablation Audit Report

## Settings
### full_oracle_evidence
- flags: `{"hide_chain_in_prompt": false, "oracle_evidence": true, "skip_chain_ranking": false, "use_event_chain": true, "use_graph": true, "use_verifier": true}`
- events_path: `data/pubevent_soa_lite/events.jsonl`
- evidence_path: `data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl`
- gold_tuples_path: `data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl`
- gold_event_chains_path: `data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl`
- model: `deepseek-v4-flash`, base_url=`https://opencode.ai/zen/go/v1`, temperature=`0.1`, max_tokens=`8000`

## Metrics
| Setting | Num-Gold | Num-Tuples | Tuple-F1-soft | Tuple-Precision | Tuple-Recall | Sentiment-Acc | Stakeholder-Recall | ESR | UTR | Candidate-UTR |
|---|---|---|---|---|---|---|---|---|---|---|
| full_oracle_evidence | 188.0000 | 119.0000 | 0.4430 | 0.5714 | 0.3617 | 0.5735 | 0.3830 | 0.7899 | 0.0924 | N/A |

## Reproducibility Checks
- PASS artifacts exist for every setting
- PASS Num-Gold is identical across settings
- PASS event_id sets are identical across settings
- PASS without_verifier ESR is N/A/null
- FAIL without_verifier Candidate-UTR/UTR separation is missing

## Delta Interpretation
- `without_event_chain` is not higher than `full` in this run.

## Paper Table Judgment
The ablation table is not paper-ready until the failed reproducibility checks above are fixed.

