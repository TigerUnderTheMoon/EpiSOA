# Experiment Plan

## Main Experiment
Run the full EpiSOA pipeline on the configured public-event evidence dataset and report attribution, evidence support, and event-chain metrics.

## Baselines
Compare EpiSOA with configured baseline methods, including direct LLM, vanilla RAG, diversity RAG, and graph-based retrieval variants.

## Ablations
Use ablation mode and config-controlled switches to disable selected modules:
- FSM collector
- diversity retrieval
- evidence graph
- event-chain retrieval
- verifier
- temporal edges
- stakeholder constraint

## Error Analysis
Generate structured error analysis for wrong stakeholders, wrong sentiment, missing evidence, unsupported rationales, and wrong event chains.

## Case Studies
Select representative cases from predictions, gold annotations, and error analysis outputs for qualitative discussion.

## Expected Outputs
- predictions.jsonl
- metrics.json
- summary.json
- ablation summaries
- error_analysis.json / error_analysis.csv / error_analysis.jsonl
- case_study_examples.json
- config snapshot
- run logs
