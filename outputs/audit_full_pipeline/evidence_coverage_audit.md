# Evidence Coverage Audit

## Summary
- Average gold evidence in prompt ratio: 0.5656
- Median gold evidence in prompt ratio: 0.5
- Average gold evidence in event-chain ratio: 0.3127
- Coverage-constrained tuple recall upper bound if extraction were perfect on any prompted gold evidence: 0.6968
- Events with zero gold evidence in prompt: []
- Events with zero gold evidence in chain: ['E002', 'E004', 'E006', 'E009', 'E010', 'E014', 'E024', 'E028', 'E030', 'E032', 'E034', 'E035', 'E042', 'E043', 'E044', 'E046', 'E049']

## P0 Zero-Prediction Events
- E001: prompt_gold=2/4, chain_gold=2/4, chain_conf=0.2089, reason=weak_chain_confidence_despite_some_gold_prompt_overlap
- E002: prompt_gold=5/7, chain_gold=0/7, chain_conf=0.0, reason=gold_evidence_absent_from_event_chain
- E010: prompt_gold=1/3, chain_gold=0/3, chain_conf=0.0, reason=gold_evidence_absent_from_event_chain
- E032: prompt_gold=3/6, chain_gold=0/6, chain_conf=0.4347, reason=gold_evidence_absent_from_event_chain
- E033: prompt_gold=3/9, chain_gold=4/9, chain_conf=0.3705, reason=llm_or_prompt_declined_extraction_despite_some_gold_prompt_overlap
- E037: prompt_gold=3/8, chain_gold=1/8, chain_conf=0.2688, reason=llm_or_prompt_declined_extraction_despite_some_gold_prompt_overlap
- E038: prompt_gold=1/5, chain_gold=2/5, chain_conf=0.6796, reason=llm_or_prompt_declined_extraction_despite_some_gold_prompt_overlap
- E047: prompt_gold=2/7, chain_gold=2/7, chain_conf=0.1281, reason=weak_chain_confidence_despite_some_gold_prompt_overlap

## Diagnosis
- Evidence selection is a major bottleneck when gold evidence is absent or thin in the prompt, but it is not the only bottleneck: several zero-prediction events still have partial gold evidence in the prompt.
- Raising `max_evidence_per_event` from 12 to 16/20 is justified for oracle diagnostics because two events have 13 unique gold evidence IDs, and a 12-evidence cap cannot include all supports.
- Add source balance, stakeholder signal, and gold-like evidence ranking. Current event-chain retrieval is keyword/source-prior based and can miss opinion-bearing support evidence.
- Oracle evidence run currently reports: {'Setting': 'full_oracle_evidence', 'Num-Gold': '188.0000', 'Num-Tuples': '119.0000', 'Tuple-F1-soft': '0.4430', 'Tuple-Precision': '0.5714', 'Tuple-Recall': '0.3617', 'Sentiment-Acc': '0.5735', 'Stakeholder-Recall': '0.3830', 'ESR': '0.7899', 'UTR': '0.0924'}
