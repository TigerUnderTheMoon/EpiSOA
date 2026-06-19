# EpiSOA 修复计划：投稿《数据分析与知识发现》前准备

## TL;DR

> **Quick Summary**: 修复 5 个 Crisis 级 + 7 个 Major 级缺陷（重新设计 verifier、修复流水线 bug、构建 held-out 测试集、重跑全部实验、论文重新定位与期刊格式合规），使项目达到投稿就绪状态。
>
> **Deliverables**:
> - 修复后的 verifier（F1-semantic@0.3 ≥ 0.35，vs without_verifier p>0.05）
> - 全部 12 个消融设置重新跑通的实验结果
> - held-out 测试集（10 事件 + gold labels）
> - 更新后的论文（标题合规、结构式摘要、诚实 IAA 描述、三线表）
> - 投稿支撑数据包（ScienceDB 就绪）
> - TDD 验证的单元测试 + 集成测试
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 5 waves
> **Critical Path**: 基线锁定 → Verifier 诊断 → Verifier 修复（TDD）→ 实验重跑 → 论文改写

---

## Context

### Original Request
用户审阅了整个 EpiSOA 项目后要求生成修复计划，针对审阅中发现的 Crisis + Major 级问题，为投稿《数据分析与知识发现》做准备。

### Interview Summary
**Key Discussions**:
- **Verifier 策略**: 选择"重新设计 verifier"——修复阈值/机制，目标使 full_soe 不再统计显著差于 without_verifier（p>0.05）
- **IAA 策略**: 选择"降级描述"——不重新标注，将流程描述为"LLM 预标注 + 三人独立专家验证"，只报告验证层面一致率
- **外部基线**: 选择"不补，纯消融"——论文重新定位为 novel task + dataset + benchmark + ablation study
- **修复范围**: 选择"Crisis + Major"——5 Crisis + 7 Major + 期刊格式
- **测试策略**: 选择 TDD——verifier 修复采用 RED-GREEN-REFACTOR

**Agreed Approach**:
- 论文重新定位：从"方法性能优越"转为"任务定义 + 数据集 + 可审计流水线 + 消融研究"
- Gold 数据冻结——不可修改
- LLM 模型版本固定——统一用于前后对照

### Research Findings
- **测试现状**: 403 个单元测试（42 个文件），零集成测试，`integration`/`real_model`/`slow`/`browser` 标记已定义但从未使用
- **verifier 架构**: `verifier/faithfulness_verifier.py` 是 `verification/faithfulness_verifier.py` 的薄包装，3 个工具函数漂移需去重
- **collect_evidence**: 是 2 行过滤器（设计如此），非空壳 bug。实际采集逻辑在 scripts/collect_evidence.py
- **流水线 bug**: direct_llm 产生 1 tuple（JSON parse 失败），oracle_evidence 产生 0 tuple（evidence selector oracle 模式损坏）
- **GENERAL_TOPIC_TERMS**: 仅别名 urban_renewal 域，其他 5 个域术语未合并

### Metis Review
**Identified Gaps** (addressed):
- **测试数量**: 修正为 403 个（非 42 个），所有均为 mock 单元测试
- **verifier 架构**: 确认为 wrapper-on-core 而非 competing duplicates，修复范围收窄为 3 个工具函数去重
- **collect_evidence**: 确认为命名混淆而非功能缺失，修复从"重构"降级为"重命名"
- **Verifier 性能预算**: 添加量化指标（F1@0.3 ≥ 0.35, rejection rate ≤ 40%）
- **Guardrails**: 添加基线锁定、Gold 冻结、API 签名不变、LLM 模型固定等约束
- **依赖风险**: 识别 verifier 在关键路径上的阻塞效应，规划并行 wave 最大化吞吐

---

## Work Objectives

### Core Objective
修复 EpiSOA 项目中所有 Crisis + Major 级缺陷，重新跑通流水线并完成论文合规改写，使项目达到投稿《数据分析与知识发现》的就绪状态。

### Concrete Deliverables
- 修复后的 verifier 模块（TDD 验证，F1 性能预算达标）
- 重新生成的实验指标（12 个 ablation settings，1 个 paper experiment）
- held-out 测试集（10 events + human gold labels）
- 更新的论文（标题 ≤20 字，结构式摘要，诚实 IAA，三线表，AI 声明）
- ScienceDB 投稿支撑数据包
- 新增集成测试 + verifier 单元测试（基于 TDD）

### Definition of Done
- [ ] `python -m pytest tests/ -q` → 403+ passed
- [ ] 全部 12 个 ablation settings 成功运行，生成 ablation_results.csv
- [ ] Verifier 性能预算达标：F1-semantic@0.3 ≥ 0.35 AND vs without_verifier p > 0.05
- [ ] 论文标题 ≤20 字，摘要含五段结构式标签，表格为三线表
- [ ] AI 使用声明、数据可用性声明、作者贡献声明齐全

### Must Have
- Verifier 修复后 full_soe 不再被自身消融统计显著证伪
- direct_llm / oracle_evidence 流水线修复（非零预测）
- held-out 测试集（≥10 events with gold）
- 论文 IAA 描述诚实降级（不报告 κ=1.0）
- 论文标题合规（≤20 字）
- 三线表 + 结构式摘要

### Must NOT Have (Guardrails)
- **不得修改 Gold 数据**（human_gold_tuples_v2.jsonl, human_gold_event_chains_v2.jsonl 不可变）
- **不得改变 verifier API 签名**（verify_tuples() 接口不变）
- **不得增删 ablation settings**（ABLATION_SETTINGS 名字/数量不变，仅补 without_verifier 到 ablation.yaml）
- **不得改动 pipeline.py 架构**（仅修复 verifier 内部逻辑）
- **不得重写整个 verifier 模块**（仅去重 3 个工具函数 + 调参 + 改 prompt）
- **不得从 scripts/ 提取采集逻辑到 src/**（仅重命名 cfsm_collector 函数）
- **不得添加新领域关键词**（仅合并现有 6 个域的 TERMS）
- **不得重写论文 Introduction/Related Work**（仅改 Results/IAA/Limitations/Abstract）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, 403 tests, markers defined)
- **Automated tests**: TDD for verifier changes
- **Framework**: pytest (Python >= 3.10)
- **TDD**: Each verifier change follows RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **CLI/Pipeline**: Use Bash (python/pytest) - Run commands, assert exit codes + outputs
- **Data/JSONL**: Use Bash (python -c) - Read JSONL, assert counts/fields/values
- **Paper/DOCX**: Use Bash (python-docx) - Read docx, assert structure/content

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation + diagnosis):
├── Task 1: 基线锁定 + git tag [quick]
├── Task 2: 添加 without_verifier 到 ablation.yaml [quick]
├── Task 3: 诊断 verifier 拒绝根因 [deep]
├── Task 4: TDD 编写 verifier 过拒测试 [deep]
├── Task 5: 构建 held-out 测试集 [quick]
└── Task 6: 合并 GENERAL_TOPIC_TERMS [quick]

Wave 2 (After Wave 1 - core fixes, MAX PARALLEL):
├── Task 7: 去重 verifier 工具函数 [quick]
├── Task 8: 修复 rule_precheck 阈值逻辑 [deep]
├── Task 9: 修复 LLM verifier prompt [deep]
├── Task 10: 修复 direct_llm 归因流水线 [deep]
├── Task 11: 修复 oracle_evidence 选择器 [quick]
├── Task 12: 添加 schema_attributor 递归防护 [quick]
└── Task 13: 修复配置模型固定 + 一致性 [quick]

Wave 3 (After Wave 2 - rerun + validate):
├── Task 14: 重跑全部 12 个消融设置 [unspecified-high]
├── Task 15: 验证 verifier 性能预算 [quick]
├── Task 16: 添加 verifier 集成测试 [deep]
├── Task 17: 添加配置模式校验测试 [quick]
├── Task 18: 重命名 cfsm_collector 函数 [quick]
└── Task 19: 用 held-out 测试集跑 paper experiment [unspecified-high]

Wave 4 (After Wave 3 - paper + journal):
├── Task 20: 重新生成全部 8 个论文表格 [quick]
├── Task 21: 改写 Results + IAA + Limitations [writing]
├── Task 22: 改写摘要 + 标题 [writing]
├── Task 23: 表格转换为三线表格式 [quick]
└── Task 24: 完成作者信息 + AI 声明 + ScienceDB [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 3 → Task 8/9 → Task 14 → Task 15 → Task 20 → Task 21 → F1-F4
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 7 (Wave 2)
```

### Agent Dispatch Summary

- **Wave 1**: 6 tasks — T1 → `quick`, T2 → `quick`, T3 → `deep`, T4 → `deep`, T5 → `quick`, T6 → `quick`
- **Wave 2**: 7 tasks — T7 → `quick`, T8 → `deep`, T9 → `deep`, T10 → `deep`, T11 → `quick`, T12 → `quick`, T13 → `quick`
- **Wave 3**: 6 tasks — T14 → `unspecified-high`, T15 → `quick`, T16 → `deep`, T17 → `quick`, T18 → `quick`, T19 → `unspecified-high`
- **Wave 4**: 5 tasks — T20 → `quick`, T21 → `writing`, T22 → `writing`, T23 → `quick`, T24 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. 基线锁定：git tag + 归档当前输出

  **What to do**:
  - 在 EpiSOA 根目录创建 git tag（如 `baseline-pre-remediation`）
  - 复制当前 `outputs/runs_human_gold_v2/` 到 `outputs/baseline_pre_remediation/`
  - 复制当前 `outputs/manuscript/` 到 `outputs/manuscript_baseline/`
  - 记录当前 git commit hash 到 `baseline_manifest.json`
  - 使 `outputs/cache/pipeline/` 对所有后续运行无效化（清空 or .gitignore）

  **Must NOT do**:
  - 不得删除或修改原 outputs/runs_human_gold_v2/
  - 不得修改 gold 数据

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["git-review"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 5, 6)
  - **Blocks**: All subsequent tasks (baseline must exist before any changes)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `outputs/runs_human_gold_v2/` — 当前实验输出，必须完整归档
  - `outputs/manuscript/episoa_full_draft.docx` — 当前论文，必须保留基线版本
  - `outputs/runs_human_gold_v2/ablation_results.csv` — 基线消融指标

  **Acceptance Criteria**:
  - [ ] `outputs/baseline_pre_remediation/` 目录存在且包含完整 artifacts
  - [ ] `outputs/manuscript_baseline/` 目录存在
  - [ ] `baseline_manifest.json` 包含 commit hash + timestamp
  - [ ] `outputs/cache/pipeline/` 已清空

  **QA Scenarios**:

  ```
  Scenario: Baseline directory contains expected files
    Tool: Bash
    Steps:
      1. Get-ChildItem -Path outputs\baseline_pre_remediation -Recurse -File | Where-Object { $_.Extension -match '\.(json|csv|jsonl)$' } | Measure-Object | Select-Object Count
      2. Test-Path -LiteralPath "outputs\baseline_pre_remediation\pubevent-soa-lite-human-gold-v2-paper\metrics.json"
    Expected Result: Count > 20 files; metrics.json exists
    Evidence: .omo/evidence/task-1-baseline-files.txt

  Scenario: Baseline manifest records correct commit
    Tool: Bash
    Steps:
      1. python -c "import json; m=json.loads(open('baseline_manifest.json').read()); print(m['git_commit'][:8])"
      2. git log --oneline -1
    Expected Result: Commit hash in manifest matches current HEAD
    Evidence: .omo/evidence/task-1-baseline-manifest.txt
  ```

  **Commit**: YES
  - Message: `chore: pin baseline before remediation (git tag + archive)`
  - Files: `baseline_manifest.json`

- [ ] 2. 添加 `without_verifier` 到 ablation.yaml 并运行诊断

  **What to do**:
  - 在 `configs/ablation.yaml` 的 `settings:` 列表中添加 `without_verifier`
  - 确保 pipeline.py ABLATION_SETTINGS 中 `without_verifier` 条目存在且配置正确（`verifier_mode: disabled`）
  - 运行 `python scripts/run_ablation.py --config configs/ablation.yaml --settings without_verifier --force`
  - 验证预期行为：without_verifier 应产生与 without_decomposed_verifier 不同（更多）的预测

  **Must NOT do**:
  - 不得删除或修改其他 ablation settings
  - 不得修改 ABLATION_SETTINGS 字典中的 without_verifier 定义（仅添加到 yaml）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 5, 6)
  - **Blocks**: Task 15 (performance budget validation needs this)
  - **Blocked By**: Task 1 (needs clean cache)

  **References**:
  - `configs/ablation.yaml:25-35` — ablation settings 列表
  - `src/episoa/pipeline.py:1265` — ABLATION_SETTINGS 中 without_verifier 条目
  - `src/episoa/pipeline.py:933-935` — 确认 without_verifier 不复用 full_soe 归因输出

  **Acceptance Criteria**:
  - [ ] `configs/ablation.yaml` settings 列表包含 `without_verifier`
  - [ ] `python scripts/run_ablation.py --settings without_verifier --force` 成功完成
  - [ ] without_verifier 的 metrics.json 中 Num-Tuples > 0

  **QA Scenarios**:

  ```
  Scenario: without_verifier produces predictions independently
    Tool: Bash
    Steps:
      1. python scripts/run_ablation.py --config configs/ablation.yaml --settings without_verifier --force
      2. python -c "import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_without_verifier/metrics.json').read()); print(m['Num-Tuples'])"
      3. python -c "import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_without_verifier/metrics.json').read()); print(m['Tuple-F1-semantic@0.3'])"
    Expected Result: Num-Tuples > 0 AND F1 > 0; NOT identical to without_decomposed_verifier
    Evidence: .omo/evidence/task-2-without-verifier-metrics.txt
  ```

  **Commit**: YES
  - Message: `config: add without_verifier to ablation settings`
  - Files: `configs/ablation.yaml`

- [ ] 3. 诊断 verifier 拒绝根因：rule_precheck vs LLM 分离分析

  **What to do**:
  - 对当前 `full_soe` 运行结果做诊断：将 verifier 拒绝分为 `rule_precheck` 拒绝和 `LLM` 拒绝两类
  - 分析 `verifier_diagnostics_all.jsonl`：统计各 `issue_flags` 出现频率
  - 确定最主要拒绝原因（如 `stakeholder_not_supported` 占 60% vs `contradiction_detected` 占 5%）
  - 对规则拒绝的元组：手动抽查 20 个被拒元组，判断规则是否过于严格
  - 对 LLM 拒绝的元组：检查 prompt 输出与 scoring 逻辑一致性
  - 生成 `verifier_rejection_analysis.json` 报告

  **Must NOT do**:
  - 不得在此阶段修改任何代码——纯诊断
  - 不得基于分析结论直接修 gold 数据

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["jsonl-data-check", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (blocks Wave 2 verifier fixes)
  - **Blocks**: Tasks 7, 8, 9 (verifier fix tasks need diagnosis results)
  - **Blocked By**: Task 1 (needs baseline outputs)

  **References**:
  - `outputs/runs_human_gold_v2/ablation_full_soe/verifier_diagnostics_all.jsonl` — 当前所有诊断记录
  - `src/episoa/verifier/faithfulness_verifier.py:278-299` — rule_precheck + _merge_issue_flags 逻辑
  - `src/episoa/verification/faithfulness_verifier.py:476-516` — 原始 rule_precheck 实现
  - `src/episoa/verifier/faithfulness_verifier.py:365-387` — VERIFIER_USER prompt

  **Acceptance Criteria**:
  - [ ] 生成 `verifier_rejection_analysis.json`，包含：
    - [ ] rule_precheck 拒绝数 vs LLM 拒绝数
    - [ ] 每个 issue_flag 的频率统计
    - [ ] Top-3 拒绝原因识别
    - [ ] 手动抽查 20 个被拒元组的结论

  **QA Scenarios**:

  ```
  Scenario: Rejection analysis generated with actionable findings
    Tool: Bash
    Steps:
      1. python -c "
  import json; from pathlib import Path
  r = json.loads(Path('verifier_rejection_analysis.json').read_text())
  print(f'Rule rejections: {r[\"rule_precheck_rejections\"]}')
  print(f'LLM rejections: {r[\"llm_rejections\"]}')
  print(f'Top flags: {r[\"top_rejection_flags\"][:3]}')
  "
    Expected Result: Both rule and LLM rejection counts > 0; top flags identified
    Evidence: .omo/evidence/task-3-rejection-analysis.txt
  ```

  **Commit**: NO (diagnostic output only, no code changes)

- [ ] 4. TDD：编写 verifier 过拒行为的失败测试

  **What to do**:
  - 基于 Task 3 诊断报告，确定最频繁的误拒模式
  - 在 `tests/` 下创建/扩展 verifier 测试文件
  - 使用 mock LLM（FakeLLMClient）编写失败测试——模拟 verifier 应该放行但当前拒绝的 case
  - 测试必须包含至少 3 个场景：rule_precheck 误拒、LLM prompt 误拒、边界阈值 case
  - 使用中文 fixtures（遵循 test_verification_verifier.py 的 pattern）
  - 运行 `python -m pytest tests/test_verifier*.py -v` → 确认新测试 FAIL

  **Must NOT do**:
  - 不得在测试中调用真实 LLM API（必须用 mock）
  - 不得修改被测代码（纯 TDD RED 阶段）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 3; starts after Task 3 provides diagnosis)
  - **Blocks**: Tasks 8, 9 (GREEN phase needs pre-existing RED tests)
  - **Blocked By**: Task 3 (needs diagnosis to know which patterns to test)

  **References**:
  - `tests/test_pipeline_verifier.py` — 现有 verifier 测试 pattern
  - `tests/test_verification_verifier.py` — verification 层测试 pattern
  - `tests/conftest.py` — 10 行 conftest，无共享 fixtures（需自行构建）
  - `src/episoa/verifier/faithfulness_verifier.py:36` — verify_tuples() 签名
  - `src/episoa/verifier/faithfulness_verifier.py:278-299` — rule_precheck 逻辑

  **Acceptance Criteria**:
  - [ ] 新测试文件创建（如 `tests/test_verifier_rejection_fix.py`）
  - [ ] ≥ 3 个测试场景：rule_precheck 误拒 / LLM 误拒 / 边界阈值
  - [ ] `python -m pytest tests/test_verifier_rejection_fix.py -v` → **FAIL** (至少 1 个测试失败，证明 bug 可复现)
  - [ ] 所有现有 403 测试仍然 PASS

  **QA Scenarios**:

  ```
  Scenario: New TDD tests fail as expected (confirming bugs are reproducible)
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_rejection_fix.py -v --tb=short 2>&1 | Select-String -Pattern "FAILED|PASSED"
    Expected Result: At least 1 FAILED test; at least 2 PASSED tests; no ERROR
    Failure Indicators: All tests PASS (bugs not reproduced) or ERROR (test infrastructure broken)
    Evidence: .omo/evidence/task-4-tdd-red.txt

  Scenario: Existing tests unaffected
    Tool: Bash
    Steps:
      1. python -m pytest tests/ -q --ignore=tests/test_verifier_rejection_fix.py
    Expected Result: All 403 existing tests PASS
    Evidence: .omo/evidence/task-4-existing-tests.txt
  ```

  **Commit**: YES
  - Message: `test: add TDD RED tests for verifier over-rejection`
  - Files: `tests/test_verifier_rejection_fix.py`

- [ ] 5. 构建 held-out 测试集（10 事件，复用已有 gold labels）

  **What to do**:
  - 从 50 个事件中选取 10 个作为 held-out 测试集（从 45 个已有 gold labels 的事件中选）
  - 在 `events.jsonl` 中将这些事件标记为 `held_out: true` 和 `split: test`
  - 确保 train/dev/test 无重叠（当前 train=40, dev=5, test=5 但有 5 个 test 事件无 gold）
  - 创建 `configs/paper_with_heldout.yaml`：data 指向 held-out events
  - 记录选取的 event_ids 到 `heldout_test_events.json`

  **Must NOT do**:
  - 不得修改 gold 元组或 gold 事件链内容
  - 不得从训练集中移除 gold labels（只标记为 held-out，实验时排除）
  - 只能从已有 gold labels 的 45 个事件中选取

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["jsonl-data-check", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 6)
  - **Blocks**: Task 19 (held-out evaluation needs this)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `data/pubevent_soa_lite/events.jsonl` — 事件注册表（含 split + held_out 字段）
  - `data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl` — gold tuples
  - `data/pubevent_soa_lite/human_gold_v2/human_gold_event_chains_v2.jsonl` — gold chains
  - `configs/paper.yaml` — 当前 paper config（需复制为 with_heldout 版本）
  - `src/episoa/config.py:32-46` — load_config 逻辑

  **Acceptance Criteria**:
  - [ ] 10 个事件被选出且全部来自有 gold labels 的 45 个事件
  - [ ] `events.jsonl` 中 split/held_out 字段正确更新
  - [ ] `configs/paper_with_heldout.yaml` 存在
  - [ ] `heldout_test_events.json` 记录选取详情

  **QA Scenarios**:

  ```
  Scenario: Held-out events have gold labels and are excluded from training
    Tool: Bash
    Steps:
      1. python -c "
  import json; from pathlib import Path
  held = json.loads(Path('heldout_test_events.json').read_text())
  print(f'Held-out events: {len(held[\"event_ids\"])}')
  gold = [json.loads(l) for l in Path('data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
  gold_events = set(t['event_id'] for t in gold)
  overlap = set(held['event_ids']) & gold_events
  print(f'Events with gold: {len(overlap)}')
  "
    Expected Result: 10 held-out events, all 10 have gold tuples
    Evidence: .omo/evidence/task-5-heldout-gold-overlap.txt

  Scenario: No overlap between train and held-out events
    Tool: Bash
    Steps:
      1. python -c "
  import json; from pathlib import Path
  events = [json.loads(l) for l in Path('data/pubevent_soa_lite/events.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
  train = [e['event_id'] for e in events if e.get('split') == 'train']
  test = [e['event_id'] for e in events if e.get('split') == 'test']
  overlap = set(train) & set(test)
  print(f'Train: {len(train)}, Test: {len(test)}, Overlap: {len(overlap)}')
  assert len(overlap) == 0, f'Overlap detected: {overlap}'
  "
    Expected Result: Train and test have zero overlap
    Evidence: .omo/evidence/task-5-split-overlap.txt
  ```

  **Commit**: YES
  - Message: `data: build held-out test set (10 events with gold labels)`
  - Files: `data/pubevent_soa_lite/events.jsonl`, `configs/paper_with_heldout.yaml`, `heldout_test_events.json`

- [ ] 6. 合并 GENERAL_TOPIC_TERMS（6 个领域术语统合）

  **What to do**:
  - 在 `src/episoa/retrieval/event_chain_retriever.py` 中修复 line 44
  - 将 `GENERAL_TOPIC_TERMS = URBAN_RENEWAL_GENERIC_TOPIC_TERMS` 改为合并所有 6 个域
  - 访问 `DOMAIN_GENERIC_TOPIC_TERMS` dict，合并 digital_governance, education, healthcare, public_safety, urban_mobility, urban_renewal 的 TERMS
  - 去重（各域 TERMS 可能有重叠）
  - 添加单元测试验证合并后 TERMS 数量 > urban_renewal TERMS 数量

  **Must NOT do**:
  - 不得添加新关键词（仅合并现有 6 个域的已有 TERMS）
  - 不得修改 DOMAIN_GENERIC_TOPIC_TERMS 结构

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 5)
  - **Blocks**: Task 14 (rerun 会用到合并后的 TERMS)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/episoa/retrieval/event_chain_retriever.py:44` — 当前仅别名 urban_renewal
  - `src/episoa/retrieval/event_chain_retriever.py:15-42` — DOMAIN_GENERIC_TOPIC_TERMS dict（6 域）

  **Acceptance Criteria**:
  - [ ] GENERAL_TOPIC_TERMS = 所有 6 域 TERMS 的并集（去重后）
  - [ ] 合并后 TERMS 数量 > URBAN_RENEWAL_GENERIC_TOPIC_TERMS 数量
  - [ ] 现有测试全部通过
  - [ ] 新增单元测试验证跨域 TERMS 完整性

  **QA Scenarios**:

  ```
  Scenario: Combined TERMS covers all 6 domains
    Tool: Bash
    Steps:
      1. python -c "
  from episoa.retrieval.event_chain_retriever import GENERAL_TOPIC_TERMS, DOMAIN_GENERIC_TOPIC_TERMS
  all_domain_terms = set()
  for domain_terms in DOMAIN_GENERIC_TOPIC_TERMS.values():
      all_domain_terms.update(domain_terms)
  print(f'Combined unique: {len(GENERAL_TOPIC_TERMS)}')
  print(f'All domain unique: {len(all_domain_terms)}')
  print(f'Urban renewal only: {len(list(DOMAIN_GENERIC_TOPIC_TERMS.values())[-1])}')
  assert len(GENERAL_TOPIC_TERMS) >= len(list(DOMAIN_GENERIC_TOPIC_TERMS.values())[-1]) * 2
  "
    Expected Result: Combined unique ≥ 2x urban_renewal only
    Evidence: .omo/evidence/task-6-terms-merge.txt
  ```

  **Commit**: YES
  - Message: `fix: merge GENERAL_TOPIC_TERMS from all 6 domains`
  - Files: `src/episoa/retrieval/event_chain_retriever.py`, `tests/test_event_chain_retriever.py`

- [ ] 7. 去重 verifier/ 与 verification/ 间的 3 个漂移工具函数

  **What to do**:
  - 对比 `verifier/faithfulness_verifier.py` 与 `verification/faithfulness_verifier.py` 中的 3 个漂移函数：
    - `loose_contains()` — verifier/ 版本有额外 token 策略
    - `support_level()` — verifier/ 版本有额外 overlap 检查
    - `evidence_span_support()` — 两个版本相同
  - 将 verifier/ 中更完善的版本移到 verification/（源模块）
  - verifier/ 从 verification/ 导入（去掉本地重复定义）
  - 验证两个模块的所有现有测试仍然通过

  **Must NOT do**:
  - 不得合并两个模块为一个（保留 wrapper-on-core 架构）
  - 不得修改 VERIFIER_RESPONSE_FORMAT 或 pipeline verifier API
  - 不得改动 verify_tuples() 签名

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 9, 10, 11, 12, 13)
  - **Blocks**: Task 14 (rerun needs de-duplicated verifier)
  - **Blocked By**: Task 3 (diagnosis confirms no architectural changes needed)

  **References**:
  - `src/episoa/verifier/faithfulness_verifier.py:50-120` — verifier/ 中 loose_contains/support_level/evidence_span_support
  - `src/episoa/verification/faithfulness_verifier.py:530-620` — verification/ 中对应函数
  - `src/episoa/verifier/faithfulness_verifier.py:16-21` — 当前从 verification/ 的导入

  **Acceptance Criteria**:
  - [ ] verifier/faithfulness_verifier.py 中不再有 loose_contains/support_level/evidence_span_support 的本地定义
  - [ ] 所有 3 个函数改为从 verification/faithfulness_verifier.py 导入
  - [ ] `python -m pytest tests/test_pipeline_verifier.py tests/test_verification_verifier.py -v` → 全部通过

  **QA Scenarios**:

  ```
  Scenario: Post-dedup tests pass
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_pipeline_verifier.py tests/test_verification_verifier.py -v
    Expected Result: All tests PASS; no import errors
    Failure Indicators: ImportError (wrong import path), AssertionError (behavior changed)
    Evidence: .omo/evidence/task-7-verifier-tests.txt

  Scenario: Functions produce identical results before/after
    Tool: Bash
    Steps:
      1. python -c "
  from episoa.verifier.faithfulness_verifier import verify_tuples
  from episoa.verification.faithfulness_verifier import rule_precheck, loose_contains
  print('All imports successful')
  print(f'loose_contains from verification: {loose_contains}')
  print(f'rule_precheck from verification: {rule_precheck}')
  "
    Expected Result: All imports succeed; verify_tuples callable
    Evidence: .omo/evidence/task-7-imports.txt
  ```

  **Commit**: YES
  - Message: `refactor: deduplicate 3 drifted utility functions between verifier/ and verification/`
  - Files: `src/episoa/verifier/faithfulness_verifier.py`, `src/episoa/verification/faithfulness_verifier.py`

- [ ] 8. 修复 rule_precheck 阈值与硬标志逻辑

  **What to do**:
  - 基于 Task 3 诊断报告，调整 `_merge_issue_flags()` 中的硬标志优先级和分值上限
  - 当前逻辑：所有硬标志触发 → 分值 cap 在 0.39 → < 0.75 threshold → 全被拒绝
  - 修复方案：
    - (a) 降低非关键标志的分值惩罚（如 `opinion_sentiment_mismatch` 从硬拒绝降为警告）
    - (b) 对 `stakeholder_not_supported` 仅在没有其他证据支持时触发（加入证据数量检查）
    - (c) 对 `contradiction_detected` 要求至少 2 条证据矛盾才触发（降低单条证据的敏感度）
  - 修复后运行 Task 4 的 TDD 测试，确认从 RED 变 GREEN

  **Must NOT do**:
  - 不得完全移除 hard_precheck_flags（保留审计能力）
  - 不得修改 verification/faithfulness_verifier.py 中的 rule_precheck 核心逻辑（仅修 verifier/ 的包装）
  - 不得将 threshold 从 0.75 改为任意值（需基于诊断数据有理有据地调整）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 9, 10, 11, 12, 13)
  - **Blocks**: Task 14 (rerun needs fixed rule_precheck)
  - **Blocked By**: Task 3 (diagnosis), Task 4 (TDD tests must exist)

  **References**:
  - `src/episoa/verifier/faithfulness_verifier.py:278-299` — _merge_issue_flags + HARD_PRECHECK_FLAGS
  - `src/episoa/verification/faithfulness_verifier.py:476-516` — rule_precheck 源逻辑
  - `verifier_rejection_analysis.json` — Task 3 生成的诊断报告

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/test_verifier_rejection_fix.py -v` → 所有 FAILED 测试变 GREEN
  - [ ] rule_precheck 拒绝率从当前水平降低 ≥ 30%（以 Task 3 诊断数据为基线）
  - [ ] HARD_PRECHECK_FLAGS 有明确的文档注释解释每个标志的触发条件

  **QA Scenarios**:

  ```
  Scenario: TDD tests pass after rule_precheck fix
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_rejection_fix.py -v --tb=short
    Expected Result: All tests PASS (zero FAILED, zero ERROR)
    Evidence: .omo/evidence/task-8-tdd-green.txt
  ```

  **Commit**: YES
  - Message: `fix: adjust rule_precheck thresholds and hard flag priorities`
  - Files: `src/episoa/verifier/faithfulness_verifier.py`

- [ ] 9. 修复 LLM verifier prompt 以降低误拒

  **What to do**:
  - 基于 Task 3 诊断报告中的 LLM 拒绝模式，修改 `VERIFIER_USER` prompt
  - 分析被 LLM 误拒的 tuple 特征（over-inference? evidence_span mismatch?）
  - 修改 prompt 使 LLM 在以下情况下更宽松：
    - stakeholder 名称略有差异但指代相同实体（"广州市白云区政府" vs "广州市政府"）
    - opinion 使用了同义表述（"反对涨价" vs "不满物业费调整"）
    - evidence_span 部分匹配但核心含义一致
  - 在 prompt 中添加 "when in doubt, favor verification" 指令
  - 降低 temperature 或添加 few-shot examples

  **Must NOT do**:
  - 不得修改 VERIFIER_RESPONSE_FORMAT（LLM 输出 schema 不变）
  - 不得让 LLM 完全跳过验证（保持 decomposed field-level check 结构）
  - 不得添加新的 API 调用或改变 verifier 的调用次数

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 10, 11, 12, 13)
  - **Blocks**: Task 14 (rerun needs fixed LLM verifier)
  - **Blocked By**: Task 3 (diagnosis), Task 4 (TDD tests)

  **References**:
  - `src/episoa/verifier/faithfulness_verifier.py:365-387` — VERIFIER_USER prompt
  - `src/episoa/verifier/faithfulness_verifier.py:355-363` — VERIFIER_SYSTEM prompt
  - `verifier_rejection_analysis.json` — LLM 拒绝模式

  **Acceptance Criteria**:
  - [ ] LLM verifier 拒绝率降低 ≥ 20%（vs Task 3 基线）
  - [ ] VERIFIER_USER prompt 包含 "when in doubt, favor verification" 指令
  - [ ] TDD 测试中 LLM 相关 case 全部 GREEN

  **QA Scenarios**:

  ```
  Scenario: TDD LLM-specific tests pass
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_rejection_fix.py -v -k "llm" --tb=short
    Expected Result: All LLM-related tests PASS
    Evidence: .omo/evidence/task-9-llm-tests.txt
  ```

  **Commit**: YES
  - Message: `fix: refine LLM verifier prompt to reduce false rejections`
  - Files: `src/episoa/verifier/faithfulness_verifier.py`

- [ ] 10. 修复 direct_llm 归因流水线

  **What to do**:
  - 诊断 direct_llm 为什么只产生 1 个 tuple（174 gold → 1 pred）
  - 检查 `method_version=direct_llm` 路径：
    - JSON parse 失败？（LLM 输出的 JSON 格式不匹配预期 schema）
    - Schema 不匹配？（direct_llm 跳过了 schema_attributor 但下游期待 SOE v3 结构）
  - 修复：为 direct_llm 添加 JSON schema 强制解析（retry with修复后的 prompt）
  - 修复：确保 direct_llm 输出能正确映射到 PredictionTuple
  - 如果问题在 LLM 响应格式，修改 prompt 添加 explicit JSON schema instruction

  **Must NOT do**:
  - 不得将 direct_llm 改为 SOE v3 pipeline（保留"直接 LLM 抽取"的语义）
  - 不得修改 PredictionTuple schema
  - 不得新增 API 调用（可在一次调用中修复 prompt）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 11, 12, 13)
  - **Blocks**: Task 14 (rerun needs fixed direct_llm)
  - **Blocked By**: Task 3 (diagnosis confirms this is code bug not fundamental limitation)

  **References**:
  - `src/episoa/pipeline.py:1195-1210` — direct_llm 的 pipeline 路径定义（ABLATION_SETTINGS）
  - `src/episoa/pipeline.py:710-740` — _run_core_pipeline 中 method_version 分支
  - `src/episoa/attribution/schema_attributor.py:400-480` — attribute_event 的 direct_llm 模式
  - `outputs/runs_human_gold_v2/ablation_direct_llm/raw_llm_responses.jsonl` — 当前 LLM 原始响应

  **Acceptance Criteria**:
  - [ ] `python scripts/run_ablation.py --settings direct_llm --force` 成功完成
  - [ ] direct_llm 的 metrics.json 中 Num-Tuples ≥ 10（至少比之前的 1 有实质提升）
  - [ ] direct_llm 的 Tuple-F1-semantic@0.3 > 0

  **QA Scenarios**:

  ```
  Scenario: direct_llm produces meaningful predictions
    Tool: Bash
    Steps:
      1. python scripts/run_ablation.py --config configs/ablation.yaml --settings direct_llm --force
      2. python -c "
  import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_direct_llm/metrics.json').read())
  print(f'Num-Tuples: {m[\"Num-Tuples\"]}')
  print(f'F1-semantic@0.3: {m[\"Tuple-F1-semantic@0.3\"]}')
  assert m['Num-Tuples'] >= 5, 'Too few predictions'
  "
    Expected Result: Num-Tuples ≥ 5, F1-semantic@0.3 > 0
    Evidence: .omo/evidence/task-10-direct-llm-fix.txt
  ```

  **Commit**: YES
  - Message: `fix: repair direct_llm attribution pipeline (JSON schema enforcement)`
  - Files: `src/episoa/pipeline.py`, `src/episoa/attribution/schema_attributor.py`

- [ ] 11. 修复 oracle_evidence 证据选择器

  **What to do**:
  - 诊断 oracle_evidence 为什么产生 0 个 tuple
  - 检查 pipeline.py ABLATION_SETTINGS 中 `oracle_evidence: True` 配置
  - 检查 `src/episoa/retrieval/evidence_selector.py` 中的 `selector_mode=oracle` 分支
  - 可能的根因：
    - oracle 模式需要 `oracle_evidence_ids_by_event` 但数据中不存在
    - oracle_evidence_ids 与实际 evidence ID namespace 不匹配
    - selector 返回空列表 → attribution 收到空输入 → 0 预测
  - 修复：确保 oracle 模式能正确读取 gold evidence IDs 并映射到当前 evidence namespace

  **Must NOT do**:
  - 不得修改 gold tuple 中的 evidence_ids
  - 不得改变 oracle_evidence 的语义（必须使用 gold evidence IDs）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 10, 12, 13)
  - **Blocks**: Task 14 (rerun needs fixed oracle_evidence)
  - **Blocked By**: None (can start immediately after Wave 1)

  **References**:
  - `src/episoa/pipeline.py:1255` — ABLATION_SETTINGS 中 oracle_evidence 条目
  - `src/episoa/retrieval/evidence_selector.py:50-80` — selector_mode 分支
  - `data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl` — gold evidence_ids 来源
  - `outputs/runs_human_gold_v2/ablation_oracle_evidence/metrics.json` — 当前 0 预测状态

  **Acceptance Criteria**:
  - [ ] `python scripts/run_ablation.py --settings oracle_evidence --force` 成功完成
  - [ ] oracle_evidence 的 metrics.json 中 Num-Tuples > 0
  - [ ] oracle_evidence 的 F1 应 ≥ full_soe（因为用的是 gold evidence）

  **QA Scenarios**:

  ```
  Scenario: oracle_evidence produces non-zero predictions
    Tool: Bash
    Steps:
      1. python scripts/run_ablation.py --config configs/ablation.yaml --settings oracle_evidence --force
      2. python -c "
  import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_oracle_evidence/metrics.json').read())
  print(f'Num-Tuples: {m[\"Num-Tuples\"]}')
  assert m['Num-Tuples'] > 0, 'Oracle evidence still broken'
  print(f'F1-semantic@0.3: {m[\"Tuple-F1-semantic@0.3\"]}')
  "
    Expected Result: Num-Tuples > 0, F1 > 0
    Evidence: .omo/evidence/task-11-oracle-evidence-fix.txt
  ```

  **Commit**: YES
  - Message: `fix: repair oracle_evidence selector mode`
  - Files: `src/episoa/retrieval/evidence_selector.py`, `src/episoa/pipeline.py`

- [ ] 12. 添加 schema_attributor._fallback_to_legacy_single_pass 递归防护

  **What to do**:
  - 在 `_fallback_to_legacy_single_pass` 中添加递归深度计数器（max_depth=2）
  - 在 `attribute_event` 中传递深度参数
  - 如果深度超限：记录错误日志 + 返回空列表（而非无限递归）
  - 添加单元测试验证递归防护（mock 反复失败的归因）

  **Must NOT do**:
  - 不得改变 _fallback_to_legacy_single_pass 的功能逻辑
  - 不得修改 attribute_event 的公共 API（深度参数仅内部使用，带默认值）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 10, 11, 13)
  - **Blocks**: Task 14 (rerun should not crash)
  - **Blocked By**: None

  **References**:
  - `src/episoa/attribution/schema_attributor.py:1288-1337` — _fallback_to_legacy_single_pass
  - `src/episoa/attribution/schema_attributor.py:710-723` — attribute_event → attribute_event_two_pass 调用链
  - `src/episoa/attribution/schema_attributor.py:1008,1040,1098` — 4 处 fallback 调用点

  **Acceptance Criteria**:
  - [ ] _fallback_to_legacy_single_pass 内部有 `if depth > max_depth: return []` 防护
  - [ ] 新增单元测试：模拟 3 次连续失败 → 预期返回 [] 
  - [ ] 所有现有测试继续通过

  **QA Scenarios**:

  ```
  Scenario: Recursion guard prevents infinite loop
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_schema_attributor.py -v -k "recursion" --tb=short
    Expected Result: Recursion guard test PASSES; function returns [] after max_depth
    Evidence: .omo/evidence/task-12-recursion-guard.txt
  ```

  **Commit**: YES
  - Message: `fix: add recursion depth guard to schema_attributor fallback`
  - Files: `src/episoa/attribution/schema_attributor.py`, `tests/test_schema_attributor.py`

- [ ] 13. 修复配置一致性：LLM 模型固定 + paper/ablation yaml 对齐

  **What to do**:
  - 确认当前 pipeline 实际使用的 LLM 模型（检查 runtime_manifest.json 或 API 日志）
  - 将 `paper.yaml` 和 `ablation.yaml` 中的 `llm_model` 统一为同一模型
  - 移除 `paper.yaml` 中 `api_key: ""` 空值（改为仅依赖 `api_key_env`）
  - 对齐两个 yaml 的以下字段：
    - `model.embedding_model`（paper 有，ablation 缺）
    - `model.reranker_model`（paper 有，ablation 缺）
    - `verifier.mode`（ablation 有，paper 缺）
    - `verifier.threshold`（两文件一致）
  - 添加运行时断言：`assert config.model.llm_model == EXPECTED_MODEL`

  **Must NOT do**:
  - 不得修改 API 密钥（保持从环境变量读取）
  - 不得更改 temperature 或其他影响实验结果的参数

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 10, 11, 12)
  - **Blocks**: Task 14 (rerun needs consistent configs)
  - **Blocked By**: None

  **References**:
  - `configs/paper.yaml:29-33` — llm_model + embedding_model + reranker_model
  - `configs/ablation.yaml:40-42` — llm_model（缺少 embedding_model/reranker_model）
  - `configs/paper.yaml:43` — `api_key: ""` 触发 placeholder 检查
  - `configs/ablation.yaml:62` — `verifier.mode: decomposed`

  **Acceptance Criteria**:
  - [ ] paper.yaml 和 ablation.yaml 中使用相同 llm_model 值
  - [ ] ablation.yaml 补齐 embedding_model + reranker_model 字段
  - [ ] paper.yaml 补齐 verifier.mode 字段
  - [ ] paper.yaml 移除 `api_key: ""` 空值行
  - [ ] `python -m episoa.cli paper-status` → 配置校验通过

  **QA Scenarios**:

  ```
  Scenario: Configs are consistent and pass validation
    Tool: Bash
    Steps:
      1. python -m episoa.cli paper-status
      2. python -c "
  from episoa.config import load_config
  p = load_config('configs/paper.yaml')
  a = load_config('configs/ablation.yaml')
  assert p.model.llm_model == a.model.llm_model, 'Model mismatch'
  assert hasattr(a.model, 'embedding_model'), 'Missing embedding_model in ablation'
  assert hasattr(p, 'verifier') and p.verifier.mode, 'Missing verifier.mode in paper'
  print('All config checks passed')
  "
    Expected Result: paper-status passes; llm_model matches; all fields present
    Evidence: .omo/evidence/task-13-config-consistency.txt
  ```

  **Commit**: YES
  - Message: `config: fix LLM model pinning and paper/ablation yaml consistency`
  - Files: `configs/paper.yaml`, `configs/ablation.yaml`

- [ ] 14. 重跑全部 12 个消融设置（--force，清除缓存）

  **What to do**:
  - 确认 `outputs/cache/pipeline/` 已清空（Task 1 已完成）
  - 运行 `python scripts/run_ablation.py --config configs/ablation.yaml --force`
  - 监控运行进度，确保全部 12 settings 完成
  - 检查每个 setting 的 `metrics.json` 中 Num-Tuples > 0
  - 特别关注：direct_llm（≥5）、oracle_evidence（>0）、without_verifier（>0）
  - 生成 `ablation_results.csv` 和 `ablation_summary.json`

  **Must NOT do**:
  - 不得更改 ablation.yaml settings 列表（已包含 without_verifier）
  - 不得使用 --resume（必须 --force 从头跑）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (sole task—depends on ALL Wave 2 fixes)
  - **Blocks**: Tasks 15, 16, 19, 20 (all need new run results)
  - **Blocked By**: Tasks 7, 8, 9, 10, 11, 12, 13 (all Wave 2 fixes)

  **References**:
  - `configs/ablation.yaml` — 12 ablation settings 配置
  - `scripts/run_ablation.py` — 消融运行脚本
  - `src/episoa/pipeline.py:1180-1380` — ABLATION_SETTINGS 定义
  - `outputs/runs_human_gold_v2/baseline_pre_remediation/ablation_results.csv` — 基线对比参照

  **Acceptance Criteria**:
  - [ ] 全部 12/12 settings 成功完成（progress.jsonl 可验证）
  - [ ] 每个 setting 的 Num-Tuples > 0
  - [ ] `ablation_results.csv` 生成且包含所有 setting 行
  - [ ] `ablation_summary.json` status 全部为 "completed"

  **QA Scenarios**:

  ```
  Scenario: All ablation settings complete with predictions
    Tool: Bash
    Steps:
      1. python -c "
  import csv; from pathlib import Path
  f = Path('outputs/runs_human_gold_v2/ablation_results.csv')
  rows = list(csv.DictReader(f.read_text(encoding='utf-8').splitlines()))
  settings = [r['Setting'] for r in rows]
  print(f'Total settings: {len(settings)}')
  zeros = [r['Setting'] for r in rows if float(r.get('Num-Tuples', 0)) == 0]
  print(f'Settings with 0 predictions: {zeros}')
  assert len(settings) == 12, f'Expected 12, got {len(settings)}'
  assert len(zeros) == 0, f'Zero-prediction settings: {zeros}'
  "
    Expected Result: 12 settings, zero with 0 predictions
    Failure Indicators: < 12 settings, or any setting with Num-Tuples=0
    Evidence: .omo/evidence/task-14-ablation-complete.csv
  ```

  **Commit**: NO (generated artifacts only, add to .gitignore)

- [ ] 15. 验证 verifier 性能预算（G2 criteria：F1 ≥ 0.35, rejection ≤ 40%, p > 0.05）

  **What to do**:
  - 从新生成的 `ablation_results.csv` 提取 full_soe 和 without_verifier 的指标
  - 运行自动化 check：
    - `full_soe Tuple-F1-semantic@0.3 ≥ 0.35`
    - `full_soe rejection_rate ≤ 40%`（从 verifier_quality_gate.json 计算）
    - `full_soe vs without_verifier` 的 paired t-test p > 0.05（使用 scripts/ 或手写 python）
  - 如果任何预算不达标：标记 FAIL，诊断原因，反馈给 Wave 2 修复循环
  - 生成 `verifier_budget_report.json`

  **Must NOT do**:
  - 不得伪造指标或人为降低检验标准
  - 不得在没有诊断的情况下直接回到 Wave 2（需先定位哪个预算不达标及原因）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 16, 17, 18)
  - **Blocks**: Tasks 20, 21 (paper needs validated numbers)
  - **Blocked By**: Task 14 (needs new ablation results)

  **References**:
  - `outputs/runs_human_gold_v2/ablation_results.csv` — 新消融指标
  - `outputs/runs_human_gold_v2/ablation_full_soe/verifier_quality_gate.json` — rejection rate 来源
  - `src/episoa/evaluation/evaluate_main.py:76-131` — semantic F1 计算位置
  - `.omo/drafts/episoa-remediation.md` — G2 预算定义

  **Acceptance Criteria**:
  - [ ] `verifier_budget_report.json` 生成
  - [ ] F1-semantic@0.3 ≥ 0.35（PASS 或 FAIL 均记录原因）
  - [ ] rejection rate ≤ 40%（PASS 或 FAIL 均记录原因）
  - [ ] p > 0.05（PASS 或 FAIL 均记录原因）

  **QA Scenarios**:

  ```
  Scenario: Verifier budget check runs and reports pass/fail
    Tool: Bash
    Steps:
      1. python -c "
  import json; from pathlib import Path
  r = json.loads(Path('verifier_budget_report.json').read_text())
  print(f'F1@0.3: {r[\"f1_semantic_03\"]} ({r[\"f1_pass\"]})')
  print(f'Rejection: {r[\"rejection_rate\"]:.1%} ({r[\"rejection_pass\"]})')
  print(f'p-value: {r[\"p_value\"]:.4f} ({r[\"p_pass\"]})')
  all_pass = r['f1_pass'] and r['rejection_pass'] and r['p_pass']
  print(f'OVERALL: {\"PASS\" if all_pass else \"FAIL\"}')
  "
    Expected Result: Report generated with all 3 checks; if FAIL, reason documented
    Evidence: .omo/evidence/task-15-budget-report.json
  ```

  **Commit**: NO (diagnostic report only)

- [ ] 16. 添加 verifier 集成测试（pipeline 级别）

  **What to do**:
  - 基于 `tests/test_verifier_rejection_fix.py` 中的 TDD 单元测试，添加集成级测试
  - 创建 `tests/test_verifier_integration.py`：
    - 使用真实 evidence fixtures 和 mock LLM
    - 测试完整的 verify_tuples() 调用链（rule_precheck → LLM → quality_gate）
    - 测试边界：空 predictions、all rejected、all passed
    - 测试 threshold sweep（0.5, 0.75, 0.9）
  - 使用 `@pytest.mark.integration` 标记（首次使用该标记）
  - 确保 `python -m pytest -m integration` 可单独运行集成测试

  **Must NOT do**:
  - 不得调用真实 LLM API
  - 不得修改 verify_tuples() 行为（仅测试，不修代码）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 15, 17, 18)
  - **Blocks**: None (validation only)
  - **Blocked By**: Task 14 (needs validated verifier state)

  **References**:
  - `tests/test_pipeline_verifier.py` — 现有 verifier 测试 pattern
  - `tests/test_verification_verifier.py` — verification 层测试 pattern
  - `tests/conftest.py` — 无共享 fixtures（需自行构建）
  - `src/episoa/verifier/faithfulness_verifier.py:36` — verify_tuples() API

  **Acceptance Criteria**:
  - [ ] `tests/test_verifier_integration.py` 创建，≥ 5 个测试用例
  - [ ] 使用 `@pytest.mark.integration` 标记
  - [ ] `python -m pytest -m integration -v` → 全部通过

  **QA Scenarios**:

  ```
  Scenario: Integration tests pass
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_integration.py -v --tb=short
    Expected Result: All tests PASS
    Evidence: .omo/evidence/task-16-integration-tests.txt
  ```

  **Commit**: YES
  - Message: `test: add verifier integration tests (pipeline level)`
  - Files: `tests/test_verifier_integration.py`

- [ ] 17. 添加配置模式校验测试

  **What to do**:
  - 创建 `tests/test_config_validation.py`：
    - 测试 paper.yaml 和 ablation.yaml 都能被 load_config() 成功加载
    - 测试两个 yaml 的 llm_model 一致
    - 测试必需字段存在（data 路径、model 配置、ablation 设置等）
    - 测试 ablation.yaml settings 列表与 ABLATION_SETTINGS 键一致
    - 测试 API key 不从配置文件泄露（key 值不以明文出现在 yaml 中）
  - 使用 `@pytest.mark.integration` 标记

  **Must NOT do**:
  - 不得在测试中打印 API 密钥
  - 不得创建新的配置文件

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 15, 16, 18)
  - **Blocks**: None
  - **Blocked By**: Task 13 (config must be consistent first)

  **References**:
  - `configs/paper.yaml` — 验证目标
  - `configs/ablation.yaml` — 验证目标
  - `src/episoa/config.py:32-46` — load_config() 实现
  - `src/episoa/pipeline.py:1180-1380` — ABLATION_SETTINGS

  **Acceptance Criteria**:
  - [ ] `tests/test_config_validation.py` 创建，≥ 5 个测试用例
  - [ ] `python -m pytest tests/test_config_validation.py -v` → 全部通过

  **QA Scenarios**:

  ```
  Scenario: Config validation catches mismatches
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_config_validation.py -v
    Expected Result: All tests PASS; config loading + consistency checks verified
    Evidence: .omo/evidence/task-17-config-tests.txt
  ```

  **Commit**: YES
  - Message: `test: add config schema validation tests`
  - Files: `tests/test_config_validation.py`

- [ ] 18. 重命名 cfsm_collector.collect_evidence → filter_evidence_by_events

  **What to do**:
  - 在 `src/episoa/collector/cfsm_collector.py` 中将 `collect_evidence` 重命名为 `filter_evidence_by_events`
  - 更新 `src/episoa/pipeline.py` 中所有导入和调用（`from episoa.collector import collect_evidence` → `filter_evidence_by_events`）
  - 检查 scripts/ 中对 cfsm_collector 的引用（如有）
  - 添加 docstring 解释：这是 2 行 evidence 过滤器，实际采集逻辑在 scripts/collect_evidence.py
  - 运行全部测试确认无导入断裂

  **Must NOT do**:
  - 不得从 scripts/collect_evidence.py 提取逻辑到 src/
  - 不得改变函数行为（只改名）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 15, 16, 17, 19)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/episoa/collector/cfsm_collector.py:8-15` — 当前 2 行 collect_evidence 函数
  - `src/episoa/pipeline.py:46` — 导入行
  - `src/episoa/pipeline.py:490` — 调用点

  **Acceptance Criteria**:
  - [ ] `cfsm_collector.py` 中函数名改为 `filter_evidence_by_events`
  - [ ] `pipeline.py` 导入和调用更新
  - [ ] `python -m pytest tests/ -q` → 全部通过
  - [ ] 函数 docstring 解释实际采集逻辑位置

  **QA Scenarios**:

  ```
  Scenario: Function rename doesn't break imports or behavior
    Tool: Bash
    Steps:
      1. python -m pytest tests/ -q
      2. python -c "
  from episoa.collector.cfsm_collector import filter_evidence_by_events
  print(f'Function: {filter_evidence_by_events.__name__}')
  print(f'Doc: {filter_evidence_by_events.__doc__[:100]}')
  "
    Expected Result: All tests pass; function importable with correct name
    Evidence: .omo/evidence/task-18-rename-verify.txt
  ```

  **Commit**: YES
  - Message: `refactor: rename cfsm_collector.collect_evidence → filter_evidence_by_events`
  - Files: `src/episoa/collector/cfsm_collector.py`, `src/episoa/pipeline.py`

- [ ] 19. 用 held-out 测试集运行 paper experiment

  **What to do**:
  - 使用 Task 5 创建的 `configs/paper_with_heldout.yaml`
  - 运行 `python scripts/run_paper_experiment.py --config configs/paper_with_heldout.yaml`
  - 确保 pipeline 从 events 中读取 split=test 的事件，使用其 gold labels 进行评估
  - 验证 held-out 评估产生非零指标（与 training set 结果对比）
  - 将 held-out 指标写入 `outputs/runs_human_gold_v2/heldout_eval/metrics.json`

  **Must NOT do**:
  - 不得用 held-out 结果反哺或调参（一次性评估）
  - 不得修改 gold 数据

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 15, 16, 17, 18)
  - **Blocks**: Task 20 (paper tables need held-out numbers)
  - **Blocked By**: Task 5 (held-out set), Task 14 (rerun config)

  **References**:
  - `configs/paper_with_heldout.yaml` — Task 5 创建的配置
  - `scripts/run_paper_experiment.py` — paper experiment 运行脚本
  - `data/pubevent_soa_lite/events.jsonl` — split=test 的事件
  - `heldout_test_events.json` — 选取的 10 个 held-out events

  **Acceptance Criteria**:
  - [ ] paper experiment 在 held-out 测试集上成功完成
  - [ ] `outputs/runs_human_gold_v2/heldout_eval/metrics.json` 存在
  - [ ] held-out Tuple-F1-semantic@0.3 > 0

  **QA Scenarios**:

  ```
  Scenario: Held-out evaluation produces valid metrics
    Tool: Bash
    Steps:
      1. python scripts/run_paper_experiment.py --config configs/paper_with_heldout.yaml
      2. python -c "
  import json; m=json.loads(open('outputs/runs_human_gold_v2/heldout_eval/metrics.json').read())
  print(f'Num-Gold: {m[\"Num-Gold\"]}')
  print(f'Num-Tuples: {m[\"Num-Tuples\"]}')
  print(f'F1-semantic@0.3: {m[\"Tuple-F1-semantic@0.3\"]}')
  assert m['Num-Gold'] > 0, 'No gold tuples in held-out set'
  assert m['Num-Tuples'] > 0, 'No predictions for held-out set'
  "
    Expected Result: Num-Gold > 0, Num-Tuples > 0, F1 > 0
    Evidence: .omo/evidence/task-19-heldout-eval-metrics.txt
  ```

  **Commit**: NO (generated artifacts only)

- [ ] 20. 重新生成全部 8 个论文表格

  **What to do**:
  - 基于 Task 14 和 Task 19 的新实验指标，重新生成论文表格
  - 更新表 1（数据集统计）：确认 50 events, 1767 evidence, 174 gold tuples, 110 gold chains
  - 更新表 4（主结果）：使用新 full_soe 指标 + 补充 held-out 评估列
  - 更新表 5（消融结果）：使用新 ablation_results.csv，确保 12 个设置完整
  - 更新表 6（证据支持细节）、表 7（链构建细节）、表 8（错误分析）
  - 统一所有表格格式为论文标准（数值保留 4 位小数，%、/ 等符号一致）
  - 输出到 `outputs/paper_tables/`（覆盖旧文件）

  **Must NOT do**:
  - 不得使用 diagnostic-only 输出中的指标
  - 不得使用 `outputs/paper_tables/` 中的旧 stale 数据
  - 不得编造或美化数字

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 21, 22, 23, 24)
  - **Blocks**: None (final deliverable)
  - **Blocked By**: Tasks 14, 19 (needs new metrics)

  **References**:
  - `outputs/runs_human_gold_v2/ablation_results.csv` — 新消融指标
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json` — 新 paper 指标
  - `scripts/build_episoa_manuscript.py` — 稿件 builder，生成表格逻辑
  - `outputs/paper_tables/paper_tables.tex` — 当前表格模板

  **Acceptance Criteria**:
  - [ ] 全部 8 个表格在 `outputs/paper_tables/` 中更新
  - [ ] 表 4 主结果包含 held-out 评估列
  - [ ] 表 5 消融结果包含全部 12 个设置
  - [ ] 所有数值与 metrics.json / ablation_results.csv 一致

  **QA Scenarios**:

  ```
  Scenario: Table numbers match source data
    Tool: Bash
    Steps:
      1. python -c "
  import csv, json; from pathlib import Path
  # Compare table values to ablation_results.csv
  t = list(csv.DictReader(Path('outputs/paper_tables/table5_ablation_results.csv').read_text(encoding='utf-8').splitlines()))
  a = list(csv.DictReader(Path('outputs/runs_human_gold_v2/ablation_results.csv').read_text(encoding='utf-8').splitlines()))
  print(f'Table settings: {len(t)}, Source settings: {len(a)}')
  assert len(t) == len(a), 'Table and source have different row counts'
  print('Row count matches')
  "
    Expected Result: Table row count = source row count
    Evidence: .omo/evidence/task-20-table-consistency.txt
  ```

  **Commit**: YES
  - Message: `docs: regenerate all 8 paper tables from new ablation results`
  - Files: `outputs/paper_tables/*`

- [ ] 21. 改写论文 Results + IAA + Limitations 部分

  **What to do**:
  - 基于更新后的实验指标，改写论文中的以下章节：
  - **Results 部分**：
    - 报告新的 full_soe 主指标（F1-semantic@0.3 等）
    - 诚实报告 verifier 的精度-召回权衡（不掩饰 verifier 过滤掉了一些正确预测）
    - 补充 held-out 测试集结果（标注"一次性评估，未用于调参"）
    - 报告消融实验中关键发现（哪些组件贡献正面，哪些组件有 trade-off）
  - **IAA 部分**：
    - 删除 κ=1.0 的声称
    - 将描述改为"LLM 预标注 + 三人独立专家验证"
    - 报告验证层面一致率（accept/reject 层面），明确标注"非内容层 IAA"
  - **Limitations 部分**：
    - 添加：数据集规模（50 events），中文专有性，基于规则检索，verifier 精度-召回权衡
    - 添加：LLM 非确定性，模型版本依赖
    - 添加：GENERAL_TOPIC_TERMS 当前仅覆盖城市更新域（已在 Task 6 修复）
  - 在 `outputs/manuscript/episoa_full_draft.docx` 中直接修改对应段落

  **Must NOT do**:
  - 不得修改 Introduction / Related Work 部分（留待后续修稿）
  - 不得声称性能优于已有方法（论文定位为任务+数据集+消融）
  - 不得保留旧指标数字

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 20, 22, 23, 24)
  - **Blocks**: None (final deliverable)
  - **Blocked By**: Tasks 14, 15, 19 (needs validated numbers)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 当前论文稿件
  - `outputs/runs_human_gold_v2/ablation_results.csv` — 新消融指标
  - `.omo/drafts/episoa-remediation.md` — IAA 降级策略描述

  **Acceptance Criteria**:
  - [ ] Results 部分引用最新指标数字（与 Task 20 表格一致）
  - [ ] IAA 部分不再出现 κ=1.0 或内容层 IAA 声称
  - [ ] Limitations 部分包含 ≥ 5 个明确限制
  - [ ] held-out 测试集结果出现在论文中

  **QA Scenarios**:

  ```
  Scenario: Paper sections no longer contain false claims
    Tool: Bash
    Steps:
      1. python -c "
  from docx import Document
  doc = Document('outputs/manuscript/episoa_full_draft.docx')
  text = ' '.join(p.text for p in doc.paragraphs)
  # Must NOT contain
  assert 'κ=1.0' not in text and 'kappa=1.0' not in text, 'IAA kappa claim still present'
  assert 'Fleiss' not in text or '验证层面' in text, 'Fleiss mentioned without downgrade context'
  print('Check 1: No false IAA claims - PASS')
  # Must contain
  assert 'held-out' in text.lower() or '保留测试' in text, 'Held-out evaluation not mentioned'
  print('Check 2: Held-out results present - PASS')
  assert '限制' in text or '局限' in text or 'Limitation' in text, 'Limitations section missing'
  print('Check 3: Limitations section present - PASS')
  "
    Expected Result: All 3 checks pass
    Evidence: .omo/evidence/task-21-paper-rewrite.txt
  ```

  **Commit**: YES
  - Message: `docs: rewrite Results/IAA/Limitations with honest numbers and positioning`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 22. 改写摘要（结构式格式）和标题（≤20 字）

  **What to do**:
  - 将当前摘要改写为结构式五段格式：【目的】【方法】【结果】【局限】【结论】
  - 每段前加粗体标签
  - 更新【结果】段为最新实验指标
  - 标记【局限】段（Exact-F1=0.0000, char@0.5=0.0550, 数据规模等）
  - 中文标题从 34 字缩短至 ≤20 字
  - 英文标题同步缩短
  - 建议标题："基于证据图谱的公共事件利益相关者意见归因"（19 字）或类似
  - 关键词保持不变（6 个）

  **Must NOT do**:
  - 不得改变摘要长度限制（≤400 字）
  - 不得删除英文摘要

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 20, 21, 23, 24)
  - **Blocks**: None
  - **Blocked By**: Tasks 14, 21 (needs validated numbers + positioned narrative)

  **References**:
  - `outputs/manuscript/episoa_outline.md:13-15` — 当前摘要
  - `outputs/manuscript/episoa_outline.md:1-3` — 当前标题
  - `outputs/manuscript/episoa_manuscript_qa.json:12-13` — 标题 34 字超限标志
  - `https://manu44.magtech.com.cn/Jwk_infotech_wk3/CN/column/column5.shtml` — 期刊格式要求

  **Acceptance Criteria**:
  - [ ] 摘要含 5 段结构式标签：【目的】【方法】【结果】【局限】【结论】
  - [ ] 中文标题 ≤ 20 字
  - [ ] 英文标题 ≤ 对应长度
  - [ ] 摘要中指标与 Task 20 表格一致

  **QA Scenarios**:

  ```
  Scenario: Title and abstract meet journal requirements
    Tool: Bash
    Steps:
      1. python -c "
  from docx import Document
  doc = Document('outputs/manuscript/episoa_full_draft.docx')
  # Find title (first heading or first paragraph)
  title = doc.paragraphs[0].text.strip()
  cn_chars = len([c for c in title if '\u4e00' <= c <= '\u9fff'])
  print(f'Title: {title}')
  print(f'Chinese chars: {cn_chars}')
  assert cn_chars <= 20, f'Title too long: {cn_chars} chars'
  # Find abstract
  for p in doc.paragraphs:
      if '【目的】' in p.text:
          assert '【方法】' in p.text and '【结果】' in p.text and '【局限】' in p.text and '【结论】' in p.text
          print('Abstract: All 5 structural labels present')
          break
  "
    Expected Result: Title ≤ 20 chars; abstract has all 5 labels
    Evidence: .omo/evidence/task-22-title-abstract.txt
  ```

  **Commit**: YES
  - Message: `docs: rewrite abstract (structured format) and shorten title to ≤20 chars`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 23. 表格转换为三线表格式

  **What to do**:
  - 将 `outputs/paper_tables/paper_tables.tex` 中的所有表格从普通 tabular 改为 booktabs 三线表
  - 使用 `\toprule`, `\midrule`, `\bottomrule` 替代 `\hline`
  - 移除表格内部的竖线（`|` 分隔符）和不必要的横线
  - 确保表题在表格上方（`\caption{}` 在 `\begin{tabular}` 之前）
  - 如果论文使用 docx 格式而非 LaTeX，则在 `episoa_full_draft.docx` 中直接调整表格样式为三线表
  - 确认 `build_episoa_manuscript.py` 中表格生成逻辑输出三线表

  **Must NOT do**:
  - 不得改变表格数据内容
  - 不得改变表格编号和标签

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 20, 21, 22, 24)
  - **Blocks**: None
  - **Blocked By**: Task 20 (needs updated tables)

  **References**:
  - `outputs/paper_tables/paper_tables.tex` — 当前 LaTeX 表格
  - `outputs/manuscript/episoa_full_draft.docx` — docx 中的表格
  - `scripts/build_episoa_manuscript.py:100-200` — 表格生成逻辑（检查是否输出三线表）

  **Acceptance Criteria**:
  - [ ] 所有表格使用三线表样式（booktabs 或 docx 等效）
  - [ ] 表格内部无竖线
  - [ ] 表题位置正确

  **QA Scenarios**:

  ```
  Scenario: Tables use 三线表 format
    Tool: Bash
    Steps:
      1. python -c "
  from docx import Document
  doc = Document('outputs/manuscript/episoa_full_draft.docx')
  tables = doc.tables
  print(f'Total tables: {len(tables)}')
  # Check first table style
  if tables:
      t = tables[0]
      print(f'Table style: {t.style.name if t.style else \"None\"}')
      print(f'Rows: {len(t.rows)}, Cols: {len(t.columns)}')
  assert len(tables) >= 4, 'Expected at least 4 tables'
  print('Table count check passed')
  "
    Expected Result: ≥ 4 tables exist
    Evidence: .omo/evidence/task-23-sanxian-table.txt
  ```

  **Commit**: YES
  - Message: `docs: convert tables to 三线表 format (journal requirement)`
  - Files: `outputs/paper_tables/paper_tables.tex`, `scripts/build_episoa_manuscript.py`

- [ ] 24. 完成期刊合规：作者信息 + 基金 + AI 声明 + ScienceDB

  **What to do**:
  - 在论文中添加/补全以下信息：
    - **作者信息**：全部作者姓名、单位、城市、邮编、ORCID（如可获取）
    - **通讯作者**：姓名 + Email
    - **基金项目**：项目名称及编号（如有省部级以上基金）
    - **作者贡献声明**：按 CRediT 分类（Conceptualization, Methodology, Software, etc.）
    - **利益冲突声明**："所有作者声明不存在利益冲突关系"
    - **AI 使用声明**：详细说明 LLM 工具使用情况（模型版本、API 提供商、使用环节、人工复核流程）
    - **数据可用性声明**："支撑数据已上传至 ScienceDB（https://www.scidb.cn/surl/dakd），包含事件注册表、证据元数据、金标准标注和实验结果摘要"
  - 准备 ScienceDB 上传数据包：
    - 从 `outputs/manuscript/submission_supporting_data/` 收集已有文件
    - 确认 events.jsonl, evidence metadata, gold tuples, benchmark 文件已包含
    - 排除原始网页全文和 LLM 原始响应（版权和隐私原因）
  - 生成 `submission_readiness_report.json` 确认所有合规项

  **Must NOT do**:
  - 不得包含作者个人信息在支撑数据包中（使用匿名版本）
  - 不得上传登录态平台内容或 raw LLM responses
  - 不得上传完整的原始网页全文（版权问题）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 20, 21, 22, 23)
  - **Blocks**: None
  - **Blocked By**: None (can start immediately)

  **References**:
  - `outputs/manuscript/episoa_outline.md:5-9` — 当前占位符作者/基金信息
  - `outputs/manuscript/submission_supporting_data/submission_readiness_report.json` — 当前合规报告
  - `https://manu44.magtech.com.cn/Jwk_infotech_wk3/CN/column/column5.shtml` — 投稿指南
  - `https://manu44.magtech.com.cn/Jwk_infotech_wk3/CN/column/column6.shtml` — 政策规范（AI 声明模板）
  - `https://www.scidb.cn/surl/dakd` — ScienceDB 推荐 URL

  **Acceptance Criteria**:
  - [ ] 论文中包含作者信息（姓名/单位/邮编/通讯邮箱）
  - [ ] 论文中包含基金项目信息（或注明"无基金资助"）
  - [ ] 论文末尾包含：作者贡献声明 + 利益冲突声明 + AI 使用声明 + 数据可用性声明
  - [ ] ScienceDB 数据包中包含 events + evidence metadata + gold + 实验结果（不含 raw data）
  - [ ] `submission_readiness_report.json` 中 `formal_results_gate_pass: true`

  **QA Scenarios**:

  ```
  Scenario: All required declarations present
    Tool: Bash
    Steps:
      1. python -c "
  from docx import Document
  doc = Document('outputs/manuscript/episoa_full_draft.docx')
  text = ' '.join(p.text for p in doc.paragraphs)
  checks = {
      'Author contribution': '作者贡献' in text or 'CRediT' in text,
      'Conflict of interest': '利益冲突' in text or 'conflict' in text.lower(),
      'AI usage': 'AI' in text or '生成式' in text,
      'Data availability': '数据可用' in text or 'ScienceDB' in text or 'data available' in text.lower(),
  }
  for check, result in checks.items():
      print(f'{check}: {\"PASS\" if result else \"FAIL\"}')
  all_pass = all(checks.values())
  assert all_pass, 'Missing declarations'
  "
    Expected Result: All 4 declarations present
    Evidence: .omo/evidence/task-24-declarations.txt
  ```

  **Commit**: YES
  - Message: `docs: complete journal compliance (author info, funding, AI, ScienceDB)`
  - Files: `outputs/manuscript/episoa_full_draft.docx`, `outputs/manuscript/submission_supporting_data/`

---

## Final Verification Wave (MANDATORY)

- [ ] F1. **Plan Compliance Audit** — `oracle`

  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files in .omo/evidence/.

  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`

  Run `python -m pytest tests/ -q`. Run lint if configured. Review all changed files for type suppression, empty catches, debug logging, commented-out code, unused imports.

  Output: `Tests [N pass/N fail] | Lint [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`

  Start from clean state. Run full pipeline: `python scripts/run_paper_experiment.py --config configs/paper.yaml && python scripts/run_ablation.py --config configs/ablation.yaml --force`. Verify all ablation settings complete. Verify verifier performance budget. Verify held-out test evaluation. Save evidence to `.omo/evidence/final-qa/`.

  Output: `Ablations [N/N complete] | Verifier Budget [PASS/FAIL] | Held-out [PASS/FAIL] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`

  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.

  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: 6 commits — `chore: pin baseline and add without_verifier`, `diagnose: verifier rejection root cause analysis`, etc.
- **Wave 2**: 7 commits — `fix: consolidate verifier utility functions`, `fix: rule_precheck thresholds`, etc.
- **Wave 3**: 6 commits — `exp: rerun full ablation suite`, `test: add verifier integration tests`, etc.
- **Wave 4**: 5 commits — `docs: regenerate paper tables`, `docs: rewrite results and IAA sections`, etc.

## Success Criteria

### Verification Commands
```bash
# All tests pass
python -m pytest tests/ -q

# Ablation suite completes
python scripts/run_ablation.py --config configs/ablation.yaml --force

# Verifier budget check
python -c "
import json; from pathlib import Path
m = json.loads(Path('outputs/runs_human_gold_v2/ablation_full_soe/metrics.json').read_text())
f1 = m['Tuple-F1-semantic@0.3']
assert f1 >= 0.35, f'F1 {f1} < 0.35'
print(f'PASS: F1-semantic@0.3 = {f1}')
"

# Paper experiment with held-out
python scripts/run_paper_experiment.py --config configs/paper.yaml
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] 403+ tests pass
- [ ] Verifier budget: F1@0.3 ≥ 0.35
- [ ] Title ≤ 20 Chinese chars
- [ ] Abstract has 5 structural labels
- [ ] Tables in 三线表 format
- [ ] AI declaration + data availability statement present
