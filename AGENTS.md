# EpiSOA Project Instructions

## Project Goal
EpiSOA is a reproducible Python research prototype for Evidence-grounded Stakeholder Opinion Attribution in public events.

The system reads local JSONL evidence, retrieves diverse evidence, builds a stakeholder-event evidence graph, retrieves event chains, generates schema-constrained attribution tuples, verifies evidence support, and evaluates results.

## Core Output Schema
The core output is:

<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>

## Development Rules
1. Do not create a new project unless explicitly requested.
2. Do not rewrite the whole codebase.
3. Prefer small, testable patches.
4. Keep business logic under src/episoa/.
5. Keep scripts/ as thin CLI wrappers.
6. Use configs for all paths, model names, thresholds, top_k, seeds, and modes.
7. Do not hardcode API keys, local absolute paths, or private data.
8. All experiment outputs must go to outputs/runs/{run_id}/.
9. mock mode is for tests and smoke tests only.
10. real mode must fail clearly when API keys are missing.
11. ablation mode must be controlled through config.
12. Run pytest after code changes when possible.

## Main Modules
- schemas
- config
- collector
- retrieval
- graph_builder
- eventrag
- reasoner
- verifier
- evaluation
- llm
- baselines
- pipeline

## Testing
Always preserve or add tests for:
- config loading
- schema validation
- pipeline smoke run
- retriever behavior
- verifier behavior
- metrics calculation

## Paper-Oriented Requirements
The code supports a research paper. It must preserve:
- reproducibility
- intermediate outputs
- clear configs
- fixed random seeds
- baseline comparison
- ablation experiments
- error analysis
- case study generation
