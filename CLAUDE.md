# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EpiSOA is a reproducible research framework for Evidence-grounded Stakeholder Opinion Attribution in public events. The output schema is `<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>`. It targets Chinese-language public events (urban renewal, public safety, etc.) with a toolchain that collects web evidence, builds event chains, generates stakeholder-opinion tuples, and verifies them via LLM-assisted faithfulness checks.

## Build & Test

```bash
# Install in editable mode
pip install -e ".[dev]"

# Run all fast unit tests (default markers from pyproject.toml)
pytest

# Run a single test file
pytest tests/test_metrics.py

# Run a single test function
pytest tests/test_metrics.py::test_tuple_f1

# Run with verbose output, showing test names
pytest -v

# Run integration tests
pytest -m integration

# Run tests that require real models (embeddings/LLM)
pytest -m real_model

# Run all tests including slow/integration
pytest -m ""
```

## Architecture

### Data Flow (Event-First Pipeline)

```
data/pubevent_soa_lite/events.jsonl    (formal event registry)
  → scripts/collect_evidence.py        (web search + C-FSM repair loop)
  → scripts/normalize_evidence.py      (QC, dedup, source classification)
  → scripts/make_annotation_sheet.py   (CSV for annotators)
  → scripts/run_llm_gold_preannotation.py
  → scripts/build_gold_review_sheets.py
  → scripts/convert_review_sheets_to_gold.py → gold_tuples.jsonl
  → scripts/validate_gold_dataset.py
  → scripts/run_paper_experiment.py    (full EpiSOA pipeline)
```

All intermediate artifacts (raw/, interim/, annotation/, evidence.jsonl, gold_*.jsonl, outputs/) are gitignored. Use `scripts/reset_workspace.py` to return to a clean data skeleton.

### Core Modules (`src/episoa/`)

| Module | Purpose |
|--------|---------|
| `data/` | Pydantic schemas (`EventRecord`, `EvidenceRecord`, `GoldTuple`, `PredictionTuple`), JSONL loader with typed validation, event validator |
| `collector/` | C-FSM evidence collection — heuristic query planner (`query_planner.py`), coverage-based repair loop (`cfsm_collector.py`), search API client (`search_client.py`), rule-based source/stakeholder/stance/temporal coverage extraction (`coverage_extractor.py`) |
| `graph/` | Builds evidence graphs linking events through shared evidence |
| `retrieval/` | Rule-based event-chain retrieval (`EventChainRetriever`) that scores evidence into 6 lifecycle stages (trigger, diffusion, conflict, response, resolution, follow_up) using keyword matching, source priors, and stakeholder signals. No LLM or gold labels involved. |
| `attribution/` | Generates candidate `<stakeholder, opinion, sentiment>` tuples from retrieved chains. `schema_attributor.py` uses LLM; `tuple_generator.py` is a simple evidence-to-prediction mapper. |
| `verification/` | LLM-assisted faithfulness verifier that checks each candidate tuple against evidence text. Strict Chinese prompts, JSON-only output, rule pre-checks before LLM calls. |
| `evaluation/` | F1, support rate metrics; evaluation harnesses for main, ablation, retrieval, and verifier. |
| `llm/` | Thin `OpenAICompatibleClient` over httpx — accepts system/user prompts, returns raw text. No LangChain. |
| `annotation/` | Gold dataset annotation tooling (preannotation prompts, review sheet builders, gold export). |
| `config.py` | `PaperConfig` dataclass from YAML; API key resolution (YAML first, then env vars with `_ENV` suffix); secret masking. |
| `pipeline.py` | Orchestrates the full paper pipeline: load config → validate data → collect → build graph → retrieve chains → generate tuples → verify → evaluate. |
| `cli.py` | `episoa` CLI entry point: `paper-status`, `run-paper`, `run-ablation`. |

### Configuration System

- YAML configs live in `configs/` (e.g., `paper.yaml`, `collector.yaml`, `ablation.yaml`)
- `configs/collector.yaml` configures the search provider and collection parameters
- `configs/source_detection.yaml` holds domain/keyword lists for rule-based source classification
- API keys are resolved via `api_key` (YAML direct) → `api_key_env` (environment variable), with placeholder detection to reject `your-*` values
- Model config uses `OpenAICompatibleClient` — any OpenAI-compatible endpoint works

### Key Design Decisions

- **No LangChain in core pipeline** — the LLM client is a thin httpx wrapper (`OpenAICompatibleClient`). `langgraph` is listed as a dependency but not used in the critical path.
- **Rule-based retrieval, not learned** — event chain retrieval and coverage extraction use hand-crafted Chinese keyword rules, domain lists, and source priors. No embeddings or neural rerankers in the default pipeline.
- **JSONL everywhere** — all data artifacts (events, evidence, tuples, chains) are line-delimited JSON with Pydantic validation on read.
- **Chinese-language NLP** — stop words, stage keywords, stakeholder terms, and LLM prompts are all in Chinese.
- **Resume support** — `collect_evidence.py --resume` skips events that already have evidence.
- **Planner is heuristic, not GA** — recent commits removed the GA planner; the collector now uses a heuristic seed-expansion + repair loop.
- **Coverage model** — the collector's repair mechanism checks source type coverage, stakeholder coverage, stance coverage, and temporal stage coverage, then issues targeted repair queries for missing dimensions.

### Common Commands (from README)

```bash
# Validate event registry
python scripts/validate_events.py

# Check paper readiness
python -m episoa.cli paper-status
python scripts/validate_paper_data.py

# Collect evidence (C-FSM with repair loop)
python scripts/collect_evidence.py
python scripts/collect_evidence.py --resume

# Full data prep pipeline after events_ready=true
python scripts/collect_evidence.py
python scripts/normalize_evidence.py
python scripts/make_annotation_sheet.py
python scripts/run_llm_gold_preannotation.py
python scripts/build_gold_review_sheets.py
python scripts/convert_review_sheets_to_gold.py
python scripts/validate_gold_dataset.py

# Run experiments after paper_data_ready=true
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation.yaml

# Reset workspace
python scripts/reset_workspace.py
```
