# Experiment Fairness Audit

| Setting | Exists | Events Raw | Predictions | Num Gold | Num Tuples | F1 | Max Tokens | Retries | Parse Failed | Raw Complete |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| full | True | 50 | 65 | 188 | 65 | 0.3083 | 3000 | 1 | 10 | True |
| without_graph | True | 50 | 73 | 188 | 73 | 0.2759 | 3000 | 1 | 9 | True |
| without_event_chain | True | 50 | 48 | 188 | 48 | 0.178 | 3000 | 1 | 15 | True |
| without_verifier | True | 50 | 74 | 188 | 74 | 0.2672 | 3000 | 1 | 8 | True |
| without_event_chain_prompt | True | 50 | 60 | 188 | 60 | 0.25 | 3000 | 1 | 11 | True |
| without_event_chain_ranking | True | 50 | 62 | 188 | 62 | 0.264 | 3000 | 1 | 9 | True |
| p0_full | True | 50 | 97 | 188 | 97 | 0.386 | 8000 | 2 | 0 | True |

## Issues
- P0 full and old full differ; final ablation table should be rerun under P0 parse repair.
- full has parse failures.
- without_graph has parse failures.
- without_event_chain has parse failures.
- without_verifier has parse failures.
- without_event_chain_prompt has parse failures.
- without_event_chain_ranking has parse failures.

## Required Answers
- Current ablation table should not be treated as the final paper table until all six settings are rerun under the same P0 parse-repair configuration.
- `without_verifier` ESR/UTR should be N/A; code supports this, but every setting must be regenerated from the same config snapshot.
- Add oracle evidence and model capability probe as diagnostic tables, not as main method comparisons.
