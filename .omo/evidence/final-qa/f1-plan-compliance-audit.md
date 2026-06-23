# F1: Plan Compliance Audit

**Date**: 2026-06-23
**Reviewer**: Sisyphus (automated)
**Plan**: `.omo/plans/episoa-resubmission.md`

## Must Have [10/10] — ALL PASS

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Verifier LLM error fallback >= 0.5 | ✅ PASS | `faithfulness_verifier.py:596` returns 0.6 |
| 2 | Verifier threshold unified (config/code) | ✅ PASS | All 9 paper configs = 0.45; code fallbacks = 0.45 |
| 3 | Title <= 20 Chinese chars | ✅ PASS | "EpiSOA：公共事件证据链观点归因" = 11 CN chars |
| 4 | AI declaration specific (model+provider+use+review) | ✅ PASS | gpt-5.5, api.asxs.top, 4 use cases, human review |
| 5 | ScienceDB package exists | ✅ PASS | 12 files in outputs/scidb_submission_package/ |
| 6 | 418+ tests pass | ✅ PASS | 427 passed (1 pre-existing fail: API-blocked) |
| 7 | TDD tests exist (3 files) | ✅ PASS | test_verifier_llm_error_fix.py, test_verifier_threshold_consistency.py, test_verifier_integration_v2.py |
| 8 | Data availability statement with ScienceDB | ✅ PASS | Para 94 mentions ScienceDB URL + contents + exclusions |
| 9 | References GB/T 7714 compliant | ✅ PASS | 35 refs, 26 [J] + 9 [C], all tagged |
| 10 | Old scripts archived (Task 33) | ✅ PASS | 21 files in outputs/manuscript/_archive_scripts/ |

## Must NOT Have [4/4] — ALL PASS

| # | Constraint | Status | Evidence |
|---|-----------|--------|----------|
| 1 | No --resume auto-enabled | ✅ PASS | run_paper_experiment.py: --resume default=None (falsy) |
| 2 | No placeholder api_key/base_url in main configs | ✅ PASS | paper.yaml, ablation.yaml, paper_with_heldout.yaml — all use env vars, no empty values |
| 3 | Gold data untouched | ✅ PASS | git diff vs baseline: 0 files changed in human_gold_v2/ or events.jsonl |
| 4 | verify_tuples() API unchanged | ✅ PASS | git diff: no signature change in faithfulness_verifier.py |

## Task Evidence Coverage [21/21] — ALL PASS

### Wave 1-2 (Tasks 1-14): 14/14 evidence files
- task-1-baseline-files.txt, task-2-tdd-red.txt, task-3-rejection-analysis.txt
- task-4-oracle-diagnosis.txt, task-5-diagnosis.txt, task-6-cleanup.txt, task-7-baseline.txt
- task-8-9-12-regression.txt, task-9-llm-tests.txt, task-10-direct-llm-fix.txt
- task-11-oracle-evidence-fix.txt, task-12-paper-yaml.txt, task-13-config-consistency.txt
- task-14-ablation-rerun.txt

### Wave 5 (Tasks 25,27,28,30,31,32,33): 7/7 evidence files
- task-25-iaa-limitations.txt, task-27-title.txt, task-28-ai-declaration.txt
- task-30-data-availability.txt, task-31-scidb-package.txt
- task-32-references.txt, task-33-cleanup.txt

## Tasks Status Summary

| Wave | Tasks | Done | Blocked | Skipped |
|------|-------|------|---------|---------|
| Wave 1 (1-7) | 7 | 7 | 0 | 0 |
| Wave 2 (8-14) | 7 | 7 | 0 | 0 |
| Wave 3 (15-20) | 6 | 0 | 6 | 0 |
| Wave 4 (21-26) | 6 | 0 | 6 | 0 |
| Wave 5 (27-33) | 7 | 6 | 0 | 1 (Task 29 author info) |
| Final (F1-F4) | 4 | 2 (F1,F2) | 1 (F3) | 0 (F4 pending) |

## Definition of Done Check

- [x] 418+ tests pass (427 passed)
- [x] Verifier LLM error fallback >= 0.5 (0.6)
- [x] Verifier threshold unified (0.45 across config + code)
- [x] Title <= 20 Chinese chars (11)
- [x] AI declaration specific (model + provider + use case + review)
- [x] ScienceDB package checklist passes
- [x] Gold data untouched
- [x] verify_tuples() API unchanged
- [ ] Main experiment = ablation_full_soe (BLOCKED: API 401)
- [ ] Verifier budget: full_soe F1 >= without_verifier OR p > 0.05 (BLOCKED: API 401)
- [ ] oracle_evidence Num-Tuples > 0 (BLOCKED: API 401)
- [ ] Held-out evaluation produced (BLOCKED: API 401)
- [ ] Paper table numbers match metrics.json (BLOCKED: API 401)
- [ ] Author info, funding, CRediT, conflict (Task 29 skipped per user)

## VERDICT

```
Must Have: 10/10 PASS
Must NOT Have: 4/4 PASS
Tasks: 21/21 evidence files present (Wave 1-2 + Wave 5)
VERDICT: APPROVE (conditional — 12 DoD items blocked by API 401, not by code/plan defects)
```

**Blocking issue**: API 401 Unauthorized (`api.asxs.top`) prevents Wave 3-4 completion. All code/config/paper-compliance work that can be done without API is complete.
