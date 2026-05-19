# AGENTS.md — EpiSOA

Reproducible research framework for Evidence-grounded Stakeholder Opinion Attribution in public events.

## Core Schema

Output: `<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>`

## Repo-Specific Setup

```bash
pip install -e ".[dev]"
```

Python >= 3.10. Entry point: `episoa` CLI (defined in `pyproject.toml`).

## Test Commands

```bash
pytest                          # fast unit tests only (default markers exclude integration/slow/real_model/browser)
pytest -m integration            # integration tests
pytest -m real_model             # tests requiring real embeddings/LLM
pytest -m ""                     # everything
pytest tests/test_metrics.py::test_tuple_f1   # single test
```

Default exclusions are set in `pyproject.toml` `[tool.pytest.ini_options]`.

## Data Flow & Command Order

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

## Architecture Notes

- **No LangChain in core pipeline.** The LLM client (`src/episoa/llm/client.py`) is a thin `httpx` wrapper (`OpenAICompatibleClient`). `langgraph` is listed as a dependency but not used in the critical path.
- **Rule-based retrieval, not learned.** Event chain retrieval and coverage extraction use hand-crafted Chinese keyword rules, domain lists, and source priors. No embeddings or neural rerankers in the default pipeline.
- **JSONL everywhere.** All data artifacts (events, evidence, tuples, chains) are line-delimited JSON with Pydantic validation on read.
- **Chinese-language NLP.** Stop words, stage keywords, stakeholder terms, and LLM prompts are all in Chinese.
- **Heuristic planner, not GA.** The collector uses a heuristic seed-expansion + repair loop. The GA planner was removed in recent commits.

## Source Scope Categories

Evidence collection uses these source categories:

- `news`: publicly accessible news pages
- `official`: public government / institutional pages
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

Defined in `src/episoa/pipeline.py` (`ABLATION_SETTINGS`). Seven settings including `full`, `without_graph`, `without_event_chain`, `without_verifier`, `full_oracle_evidence`, and chain-prompt/ranking ablations. Each setting runs the full pipeline independently in its own directory.

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
  retrieval/     # Rule-based event-chain retriever (6 lifecycle stages)
  attribution/   # Tuple generation from chains (LLM schema attributor + simple mapper)
  verification/  # LLM-assisted faithfulness verifier
  evaluation/    # F1, support rate, ablation eval harnesses
  llm/           # Thin OpenAI-compatible client over httpx
  annotation/    # Gold dataset annotation tooling
  config.py      # PaperConfig dataclass, API key resolution
  pipeline.py    # Full paper pipeline orchestrator
  cli.py         # `episoa` CLI entry point
```

## Generated Artifacts

All intermediate artifacts (`raw/`, `interim/`, `annotation/`, `evidence.jsonl`, `gold_*.jsonl`, `outputs/`) are gitignored. Use `scripts/reset_workspace.py` to return to a clean data skeleton.

## Gotchas

- `coverage.json` is a JSON snapshot (read with `json.load`, not as JSONL).
- The collector writes planner diagnostics to `data/pubevent_soa_lite/interim/query_planner_debug.json`.
- Paper runs write to `outputs/runs/{run_id}/` with predictable filenames (`metrics.json`, `summary.json`, `main_results.csv`, etc.).
- `events.jsonl` must contain only accepted concrete public events with factual locations, time windows, triggers, structured anchor entities, anchor URLs, source scopes, and query seeds.
