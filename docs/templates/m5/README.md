# M5 annotation template headers

These files mirror the executable EpiSOA-EA Gold workflow. Copying a header does not create Gold; use `prepare-ea-gold` whenever source records are available.

- `document_annotations.csv`: A/B source-level Effect, Claim, and Evidence decisions; supports `human_decision=add`.
- `document_disagreements.csv`: C-only document-level disagreements.
- `canonical_adjudication.csv`: C-only `needs_adjudication` decisions.
- `fusion_pair_annotations.example.jsonl`: field example for A/B Fusion Gold; replace all placeholder values.

See `docs/m5_gold_template_guide.md` for constraints.
