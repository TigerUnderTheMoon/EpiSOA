# AGENTS.md — EpiSOA

Reproducible research framework for Evidence-grounded Stakeholder Opinion Attribution in public events.

## Frozen Target Method

The paper's frozen target method is **EpiSOA-EA: Stakeholder-Centered Explanatory Attribution with Field-Level Evidence Grounding**.

Authoritative specifications:

- `docs/method_framework.md` — frozen paper method, research scope, data model, baselines, ablations, and metrics.
- `docs/annotation_guidelines.md` — executable human-annotation and gold-data rules.
- `docs/m5_pilot_protocol.md` — six-event Pilot execution, hard gates, stop rules, and review decisions.
- `configs/ea_pilot_events.yaml` — frozen six-event Pilot registry and authoritative anchor URLs.
- `configs/ea_pre_pilot_fairness.yaml` — pre-pilot shared-model and comparison-method contract.

These documents define the **v1.5 target design**, not paper-readiness status. The legacy `soe_v3` pipeline remains available, while the isolated `src/episoa/ea/` path implements the offline Document Understanding, source-record verification, APCF/Fusion, Event Dossier, Gold, baseline-adapter, and evaluation contracts with synthetic tests. This does not constitute six-event Pilot evidence, validated human Gold, real-API baseline results, or Formal results. Do not claim paper-experiment readiness until the M5 Pilot and all later frozen gates pass.

Non-negotiable target-method boundaries:

- Formal relations are limited to `stance_rationale`, `emotion_trigger`, and `action_motivation`; `no_relation` is a candidate-decision label only.
- The actual application unit is one concrete multi-source public event. The final target output is a provenance-aware, field-evidence-grounded Event Dossier whose formal information model is the Event Opinion Graph; JSONL files are its serialization, not isolated final products.
- Keep `effect_stage` and `claim_stage` separate.
- Use document-level extraction and event-level aggregation. Every Document independently produces 0-N Effects, Claims, and Evidence Links; every source-level record must retain document/source provenance and field-level Evidence Spans before within-event normalization.
- Keep EffectHolder, AttributionHolder, and ReportingSource separate. EffectHolder requires a non-empty, evidence-grounded `holder_surface`; Claim `attribution_holder_surface` is nullable for implicit or genuinely unexpressed surfaces, but any non-null value requires Evidence. Surface fields support human understanding and traceability, while the frozen nine-class categories support normalization, canonicalization, and evaluation. This does not create a person-level cross-document entity-resolution task.
- ReportingSource references `sources.jsonl`; it remains a concrete source-level record and does not reuse holder categories.
- `evidence_links` must support both Effect and Claim targets.
- `verified` means that the text supports the attributed explanation, not that the explanation is a true real-world cause.
- `primary_source_id` is the v1.5 source-lineage deduplication key and `derivation_type` records document derivation. Do not add a Claim-level `source_independence` or `partially_independent` state layer.
- Cross-source status belongs at Claim Pair or Claim Group level, not on a source-level Claim.
- Formal Claim rows do not contain constant `relation_decision=supported`.
- Only `verified` records enter formal `attribution_claims.jsonl`; all verification outcomes remain in `verification_diagnostics.jsonl`.
- Canonical Effect represents a category-level viewpoint proposition, not actor coreference. Event, stakeholder category, Effect type, closed Effect value, Action value, and Target are compatibility dimensions rather than one exact composite key; Action values and Targets may use shared semantic judgments. Stage is an observation attribute and produces `observed_stages`.
- Canonical IDs are generated from deterministically sorted cluster membership, not by hashing structural fields. M3 source records do not contain program Canonical IDs; Fusion publishes membership. Only `needs_adjudication` cases enter C review, which is not an extra annotation layer.
- Keep `semantic_label` separate from `merge_decision`. Semantically equivalent explanations may remain in different Canonical Claim Groups when AttributionHolder is incompatible, while their group-level `equivalent_explanation` relation is preserved.
- APCF is false-merge-averse constrained aggregation: every required cross-cluster pair must be `must_link`; any `cannot_link`, `needs_adjudication`, or missing pair blocks automatic merging.
- APCF is defined by Redundancy reduction, Attribution preservation, Disagreement preservation, and Provenance preservation. It never performs Truth Fusion.
- Canonicalization must preserve every source-level Effect/Claim, including holder surface, Document, Source, Evidence, polarity, and certainty. One stakeholder category may have several conflicting CanonicalEffects; never collapse them into an aggregate "public stance" or a single true explanation.
- Create Stance or Emotion Effects only when the corresponding expression exists. `uncertain` means an expressed stance/emotion cannot be classified reliably, not that the field is absent; Emotion `neutral` requires an actual non-polar emotional state, and factual statements do not create Emotion Effects.
- `Relation Decision Macro-F1` is computed on one fixed gold candidate set with labels `stance_rationale`, `emotion_trigger`, `action_motivation`, and `no_relation`; end-to-end output is evaluated separately with `Attribution Claim F1`.
- The Main comparison methods are Long-context Event LLM, Long-context + Evidence, Direct Explanation-Effect Pair Classification, Original EpiSOA, and EpiSOA-EA. Only the two Long-context methods and EpiSOA-EA support full Dossier comparison; Direct Pair is a Relation Decision subtask baseline and Original EpiSOA is historical/legacy. Do not score unsupported outputs as fabricated Dossier results.
- Exact, Embedding, LLM Pairwise, and APCF share Gold, candidate pairs, normalizer, splits, and metrics. LLM Pairwise and APCF additionally consume the identical versioned semantic-pair judgment resource produced with the same base LLM, prompt, temperature, and decoding parameters; APCF may not make an extra semantic call.
- Before any Formal inference, tokenize all frozen 60-event inputs plus prompts and reserved output budget, select and freeze one capacity-sufficient base model/version for Long-context and EpiSOA-EA, and forbid silent truncation or performance-driven model replacement.
- Report Cross-document Attribution Contamination Rate as a core diagnostic, especially for Long-context Event-level LLM versus EpiSOA-EA. It measures predicted Claims that combine holder, explanation, attribution holder, or evidence from different Documents into a relation absent from every source document.
- Dataset scale is frozen at 6 Pilot Events plus 60 Formal Events, for 66 total processed events. Pilot uses one event from each of urban renewal, education, healthcare, public safety, urban transport, and digital governance only for M5 annotation/prompt/pipeline validation and never enters the formal Test set. Formal experiments use 10 events from each of those six domains and approximately 360–480 Documents in total.
- Pilot and Formal Events use criterion-based purposive sampling plus maximum variation sampling. Freeze all 60 Formal Events before Gold construction and model evaluation; never select or replace events based on model performance.
- Formal reporting has three levels: pooled instance metrics, event-level mean/median/dispersion, and 95% event-cluster Bootstrap confidence intervals. Method comparisons use paired Event Bootstrap over the identical 60 Formal Events.
- The 60 Formal Events are a benchmark corpus for cross-context stability, not 60 shallow application outputs. Add a preselected 1-2 event Event Dossier Case Study covering stakeholder-effect structure, self/external attribution, source-claim structure, and stage evolution without objective causal inference.
- Do not add LightRAG, EventRAG, GraphRAG, complex graph learning, extra LLM modules, Truth Fusion, or new relation types without an explicit user decision.
- Do not add general event causality, counterfactual inference, responsibility adjudication, or new method modules without an explicit user decision.

## Current Legacy Implementation Schema

The following schema describes the current `soe_v3` code, not the frozen EpiSOA-EA target:

Output: `<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>`

## Repo-Specific Setup

```bash
pip install -e ".[dev]"
```

Python >= 3.10. Entry point: `episoa` CLI (defined in `pyproject.toml`).

## Test Commands

```bash
python -m pytest                          # fast unit tests only (default markers exclude integration/slow/real_model/browser)
python -m pytest -m integration            # integration tests
python -m pytest -m real_model             # tests requiring real embeddings/LLM
python -m pytest -m ""                     # everything
python -m pytest tests/test_metrics.py::test_tuple_f1   # single test
```

Prefer `python -m pytest` in this Windows workspace so the repository root is on `sys.path` and `scripts.*` test imports resolve consistently.

Default exclusions are set in `pyproject.toml` `[tool.pytest.ini_options]`.

## Current Legacy Data Flow & Command Order

The pipeline is strictly ordered. Do not skip steps.

```
events.jsonl (formal event registry)
  -> scripts/collect_evidence.py
  -> scripts/normalize_evidence.py
  -> scripts/make_annotation_sheet.py
  -> scripts/run_llm_gold_preannotation.py   # generates llm_gold_* silver/pseudo-gold
  -> scripts/export_silver_benchmark.py
  -> scripts/build_human_adjudication_sheet.py
  # after human review:
  -> scripts/convert_adjudication_to_human_gold.py
  -> scripts/audit_human_gold.py
  -> scripts/validate_gold_dataset.py
  -> scripts/run_paper_experiment.py --config configs/paper.yaml
  -> scripts/run_ablation.py --config configs/ablation.yaml --force
```

**Critical distinction:** `llm_gold_tuples.jsonl` and `llm_gold_event_chains.jsonl` are **LLM preannotation (silver/pseudo-gold)**, NOT final human-verified gold. Do not treat them as ground truth for paper experiments without going through the human adjudication pipeline.

## Key Commands

| Task | Command |
|------|---------|
| Validate events | `python scripts/validate_events.py` |
| Check readiness | `python -m episoa.cli paper-status` |
| Collect evidence | `python scripts/collect_evidence.py` |
| Resume collection | `python scripts/collect_evidence.py --resume` |
| Reset workspace | `python scripts/reset_workspace.py` |
| Paper experiment | `python scripts/run_paper_experiment.py --config configs/paper.yaml` |
| Ablation | `python scripts/run_ablation.py --config configs/ablation.yaml --force` |

`--resume` on `collect_evidence.py` skips events that already have evidence. `--force` on `run_ablation.py` removes existing per-setting output directories before re-running.

## Current Legacy Architecture Notes

- **No LangChain in core pipeline.** The LLM client (`src/episoa/llm/client.py`) is a thin `httpx` wrapper (`OpenAICompatibleClient`). `langgraph` is listed as a dependency but not used in the critical path.
- **Rule-based retrieval, not learned.** Event chain retrieval and coverage extraction use hand-crafted Chinese keyword rules, domain lists, and source priors. No embeddings or neural rerankers in the default pipeline.
- **Main method is `soe_v3`, no GNN.** The paper main path uses a rule-derived evidence graph as an auditable skeleton, `coverage_optimized` evidence selection, two-pass SOA attribution, `soe_graph/` materialization, and decomposed verifier diagnostics.
- **Stakeholder-canonical attribution.** The formal `SchemaAttributor` runs with `attribution_mode=stakeholder_canonical`: it clusters event-level stakeholders and emits one canonical tuple per evidence-supported stakeholder by default. It may emit multiple tuples for the same `stakeholder_cluster_id` only when `opinion_split_reason` explains distinct opinions/actions.
- **Two-pass SOA attribution.** For `method_version=soe_v3`, attribution first writes stage-level candidates to `stage_soa_candidates.jsonl`, then merges them into stakeholder-canonical final tuples in `candidate_soa_tuples.jsonl`. Parse failure retries once and then falls back to legacy single-pass attribution with `fallback_mode=legacy_single_pass`.
- **No event-level tuple target.** `max_tuples_per_event` is deprecated for formal attribution and must not be interpreted as a generation cap or target. Manifests report `tuple_limit_policy: none` and may keep `max_tuples_per_event_deprecated_noop` only for backward-compatible config reading.
- **Coverage-optimized evidence selection.** The paper main path uses `selector_mode=coverage_optimized`, balancing event relevance, chain stage score, stakeholder/stage/source-family coverage, opinion-bearing signal, and quality score while penalizing near-duplicate text/title evidence. Candidate coverage diagnostics are written into `request_summary` / `selection_diagnostics`.
- **Candidate constraints are audit signals, not hard gold filters.** Graph stakeholder candidates guide extraction, but evidence-supported stakeholders missing from the graph are allowed and marked `stakeholder_candidate_match_status=unmatched`.
- **Field-level verification.** Decomposed verifier output includes `verification_diagnosis` with stakeholder, opinion, sentiment, rationale, evidence-span, temporal-stage, over-inference, and contradiction checks.
- **JSONL everywhere.** All data artifacts (events, evidence, tuples, chains) are line-delimited JSON with Pydantic validation on read.
- **Chinese-language NLP.** Stop words, stage keywords, stakeholder terms, and LLM prompts are all in Chinese.
- **Heuristic planner, not GA.** The collector uses a heuristic seed-expansion + repair loop. The GA planner was removed in recent commits.

## Human Gold Sheet Naming

Independent human review tuple sheets are annotator-specific:

- `annotator_A/humanA_tuple_adjudication_sheet.csv`
- `annotator_B/humanB_tuple_adjudication_sheet.csv`
- `annotator_C/humanC_tuple_adjudication_sheet.csv`

The chain sheet name remains `human_chain_adjudication_sheet.csv` inside each annotator directory. These renamed tuple files are content-preserving replacements for the older per-annotator `human_tuple_adjudication_sheet.csv` files.

## Source Scope Categories

Evidence collection uses these source categories:

- `news`: publicly accessible news pages
- `official`: public government / institutional pages
- `public_interaction`: government-citizen interaction platforms (领导留言板, 12345 hotlines, 政民互动)
- `forum`: public forum and discussion pages
- `public_social`: public social-media-related pages, search-indexed post snippets, or social-media content quoted by news/forums/aggregators
- `public_web`: other publicly accessible web pages

**`public_social` does NOT include:** non-public content only visible after signing in, internal comment areas, short-video comment threads, or complete note data from platforms such as Douyin, Xiaohongshu, or Weibo.

## API Configuration

API keys resolve via `resolve_api_config()` with **YAML-first precedence**:

1. `api_key` / `base_url` in YAML config
2. Environment variable named by `api_key_env` / `base_url_env`
3. Placeholder values starting with `your-` are rejected

Runtime status prints only the source and a masked key; never the full key.

## Ablation Settings

Defined in `src/episoa/pipeline.py` (`ABLATION_SETTINGS`). Each setting runs the full pipeline independently in its own directory and writes prompt/input manifests. Ablation interpretation should use the manifest fields (`attribution_mode`, `tuple_limit_policy`, selected evidence IDs, prompt flags, verifier flags) rather than relying on legacy config names.

## Project-Specific Skills

Repo-local OpenCode skills live in `.opencode/skills/`:

- `episoa-quality-gate` — dataset quality gates
- `jsonl-data-check` — validate JSONL datasets
- `python-debug` — debug Python scripts
- `repo-map` — map repository structure
- `safe-edit` — safe minimal code edits
- `git-review` — review git status and diffs

## Monorepo / Package Boundaries

```
src/episoa/
  data/          # Pydantic schemas, JSONL loader, validator
  collector/     # C-FSM evidence collection (heuristic planner, repair loop, search client, coverage extractor)
  graph/         # Evidence graph linking events through shared evidence
  retrieval/     # Rule-based event-chain retriever (6 lifecycle stages) + evidence selector + deterministic reranker
  attribution/   # Tuple generation from chains (LLM schema attributor; tuple_generator.py is deprecated)
  verification/  # Full LLM-assisted faithfulness verifier (used by scripts and tests; pipeline uses verifier/ instead)
  verifier/      # Pipeline-integrated faithfulness verifier (id_only and decomposed modes)
  evaluation/    # F1, support rate, ablation eval harnesses
  llm/           # Thin OpenAI-compatible client over httpx
  annotation/    # Gold dataset annotation tooling
  utils/         # I/O helpers, logging configuration
  config.py      # PaperConfig dataclass, API key resolution
  pipeline.py    # Full paper pipeline orchestrator
  cli.py         # `episoa` CLI entry point
```

## Generated Artifacts

All intermediate artifacts (`raw/`, `interim/`, `annotation/`, `evidence.jsonl`, `gold_*.jsonl`, `outputs/`) are gitignored. Use `scripts/reset_workspace.py` to return to a clean data skeleton.

## Gotchas

- `coverage.json` is a JSON snapshot (read with `json.load`, not as JSONL).
- The collector writes planner diagnostics to `data/pubevent_soa_lite/interim/query_planner_debug.json`.
- Paper runs write to `outputs/runs_human_gold_v2/{run_id}/` (configured in `paper.yaml`) with predictable filenames (`metrics.json`, `summary.json`, `main_results.csv`, etc.).
- `events.jsonl` must contain only accepted concrete public events with factual locations, time windows, triggers, structured anchor entities, anchor URLs, source scopes, and query seeds.
