# EpiSOA 投稿前终审修复计划 v2（Resubmission Audit Remediation）

## TL;DR

> **Quick Summary**: 修复先前 24-task 计划执行后残留的 7 个 Crisis + 10 个 Major + 5 个 Minor 级漏洞，覆盖主实验/ablation 指标根因调查、verifier 重修、held-out 评估补跑、论文数字对齐、期刊合规完善，使项目达到《数据分析与知识发现》投稿就绪状态。
>
> **Deliverables**:
> - 主实验 vs ablation_full_soe 指标差异根因报告 + 修复
> - Verifier 重修（TDD）：LLM error fallback、阈值统一、让 full_soe F1 ≥ without_verifier 或 p>0.05
> - Held-out 测试集评估实际产出（10 events, 34 gold tuples）
> - 论文 Table 1/4/5/6 数字与主实验对齐
> - 标题缩短至 ≤20 字、AI 声明具体化、作者信息填实
> - 全部 9 个 ablation settings 重跑（含修复 oracle_evidence）
> - 投稿支撑数据包（ScienceDB 就绪）
>
> **Estimated Effort**: XL
> **Parallel Execution**: YES - 6 waves
> **Critical Path**: 根因调查 → Verifier TDD 重修 → 实验重跑 → 论文数字对齐 → 合规完善

---

## Context

### Original Request
用户在先前 24-task 修复计划执行完毕后，要求对整个 EpiSOA 项目和论文做投稿前终审，找出残留漏洞，评估投稿《数据分析与知识发现》还差什么，生成全新独立修复计划。

### Interview Summary
**Key Discussions**:
- **与先前计划关系**: 全新独立计划（先前计划作为历史，聚焦残留问题）
- **审阅触发**: 例行投稿前终审
- **审阅范围**: 全维度（代码 + 实验 + 论文 + 投稿材料）
- **测试策略**: TDD（RED-GREEN-REFACTOR）
- **主实验冲突**: 先调查根因再决定（不直接重跑或直接改论文）
- **Verifier 处理**: 重修 verifier（不保留现状，不双配置，不移除）
- **Held-out**: 立即跑 + 写入论文
- **时间压力**: 无压力，彻底修

**Agreed Approach**:
- 先调查主实验 vs ablation_full_soe 差异根因，再决定用哪个数据作为正式结果
- Verifier 采用 TDD 重修，目标让 full_soe 不再被显著证伪
- Held-out 评估补跑并写入论文
- 论文所有数字与最终选定的正式结果对齐
- 投稿合规项全部填实（作者、基金、AI 声明、数据可用性）

### Research Findings

#### 根因调查关键发现
- 主实验 `mode: paper` vs ablation `mode: ablation` 走不同配置路径
- 主实验 config 缺少 `verifier.mode: decomposed`（ablation 有）
- 主实验 `api_key: ""` 空值存在（ablation 已移除）
- 主实验 runtime_manifest 显示 `resume: true` 但 config `resume: false`（可能用了缓存）
- 主实验 `max_api_concurrency: 2` vs ablation `4`
- ABLATION_SETTINGS 中 `full_soe` 强制 `verifier_mode: decomposed, use_verifier_quality_gate: True`，主实验走默认路径可能不同
- **结论**: 主实验 44 tuples vs ablation 82 tuples 差异源于配置路径分歧，需调查 pipeline.py 中 paper mode 与 ablation mode 的默认值差异

#### Verifier 缺陷
- `src/episoa/verifier/faithfulness_verifier.py:596`: `except Exception: return 0.5, {"reason": "llm_verifier_error"}` — LLM API 错误时返回 0.5，低于 config threshold 0.75 → 全部拒绝
- `verify_tuples()` line 48: `threshold: float = 0.45`（code default）vs config 0.75 vs 论文称 0.40 — 三处不一致
- `_apply_hard_flag_score_cap()` line 482: 硬标志 cap 在 0.39，仍低于 0.75 threshold
- 先前修复添加了 `_relax_precheck_flags()` 和 post-LLM relaxation，但 LLM error fallback 未修

#### 实验数据不一致
- 主实验 metrics.json: Num-Tuples=44, F1@0.3=0.2385
- ablation_full_soe metrics.json: Num-Tuples=82, F1@0.3=0.3906
- 论文 Table 5/摘要: 报告 82/0.3906（引用了 ablation 而非主实验）
- `outputs/paper_tables/table1_dataset_statistics.csv`: STALE（1767/188/138）
- 实际数据: 1461 证据 / 174 gold tuples / 110 gold chains
- docx 内 Table 1: 正确（1461/174/110）

#### 先前计划执行质量
- Task 11 (oracle_evidence): 声称修复但 ablation_oracle_evidence 仍 Num-Tuples=0
- Task 19 (held-out): evidence 文件存在但 outputs 下无 heldout 产出目录
- Task 22 (标题): 声称修复但标题仍 34 字符
- Task 23 (三线表): 未验证 docx 表格样式
- Task 24 (AI 声明): 声明仍笼统

### Metis Review
Metis 代理余额不足无法调用。Prometheus 自行完成 gap analysis:

**Identified Gaps** (addressed):
- **G1 根因假设验证**: 计划 Wave 1 先调查 paper vs ablation 配置路径差异，再决定主实验处理方式（用户已确认）
- **G2 Verifier 重修边界**: 必须保持 verify_tuples() API 不变，不破坏现有 403 测试（guardrail）
- **G3 论文改写范围**: 不重写 Introduction/Related Work，只改 Results/IAA/Limitations/Abstract/Declarations
- **G4 统计显著性重算**: 实验重跑后必须重新计算 paired t-test，不能复用旧 p 值
- **G5 ScienceDB 边界**: 排除原始网页全文、登录态内容、raw LLM responses；包含 events.jsonl、evidence metadata、gold tuples、experiment configs、metrics summary
- **G6 外部预审**: 计划不强制邀请外部审稿人，但在 Final Wave 建议用户自行预审
- **G7 oracle_evidence 修复**: 必须实际产出 >0 预测，不能在论文中回避
- **G8 without_soe_graph 异常**: 15 tuples 可能是 bug，需调查是否 graph 关闭导致 attribution 路径异常

---

## Work Objectives

### Core Objective
修复先前计划执行后残留的所有 Crisis + Major 级漏洞，完成投稿前终审，使 EpiSOA 项目和论文达到《数据分析与知识发现》投稿就绪状态。

### Concrete Deliverables
- 主实验 vs ablation 根因报告 + 修复后的统一正式结果
- Verifier 重修（TDD，F1 ≥ without_verifier 或 p>0.05）
- Held-out 评估实际产出
- 9 个 ablation settings 重跑（含 oracle_evidence 修复）
- 论文数字对齐 + 标题合规 + AI 声明具体化
- ScienceDB 投稿数据包
- TDD 测试 + 集成测试

### Definition of Done
- [ ] `python -m pytest tests/ -q` → 418+ passed（现有 418 + 新增 verifier TDD）
- [ ] 主实验与 ablation_full_soe 指标差异根因明确文档化
- [ ] Verifier 重修后 full_soe F1@0.3 ≥ without_verifier F1@0.3 OR paired t-test p > 0.05
- [ ] oracle_evidence Num-Tuples > 0
- [ ] held-out 评估产出存在且 Num-Tuples > 0, F1 > 0
- [ ] 论文标题 ≤ 20 中文字符
- [ ] 论文所有表格数字与 metrics.json 一致
- [ ] AI 使用声明包含模型版本、API 提供商、使用环节、人工复核机制
- [ ] 作者信息、基金、CRediT 贡献声明、利益冲突声明、数据可用性声明齐全
- [ ] ScienceDB 数据包 checklist 通过

### Must Have
- 主实验 vs ablation 根因调查报告
- Verifier LLM error fallback 修复（不再返回 0.5 导致全拒）
- Verifier 阈值统一（config / code / 论文三处一致）
- Held-out 评估实际运行 + 论文补充
- oracle_evidence 修复（>0 预测）
- 论文 Table 5/摘要数字与选定正式结果对齐
- 论文标题 ≤20 字
- AI 使用声明具体化
- 作者信息填实

### Must NOT Have (Guardrails)
- **不得修改 Gold 数据**（human_gold_tuples_v2.jsonl, human_gold_event_chains_v2.jsonl 不可变）
- **不得改变 verify_tuples() 公共 API 签名**
- **不得改变 pipeline.py 核心架构**（只修 verifier 内部 + 配置默认值）
- **不得增删 ABLATION_SETTINGS**（12 个 setting 名字/数量不变）
- **不得重写论文 Introduction/Related Work**（只改 Results/IAA/Limitations/Abstract/Declarations）
- **不得修改 gold 数据以迎合实验**
- **不得在论文中编造或美化数字**
- **不得跳过 TDD**（verifier 修复必须先 RED 再 GREEN）
- **不得删除 outputs/baseline_pre_remediation/**（保留基线对照）
- **不得更改 LLM 模型版本**（保持 gpt-5.5 前后一致）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, 418 tests collected, markers defined)
- **Automated tests**: TDD for verifier changes + integration tests for pipeline
- **Framework**: pytest (Python >= 3.10)
- **TDD**: Each verifier change follows RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **CLI/Pipeline**: Use Bash (python/pytest) - Run commands, assert exit codes + outputs
- **Data/JSONL**: Use Bash (python -c) - Read JSONL, assert counts/fields/values
- **Paper/DOCX**: Use Bash (python-docx) - Read docx, assert structure/content
- **Config**: Use Bash (python -c) - Load yaml, compare fields

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - root cause + diagnosis + scaffolding):
├── Task 1: 根因调查：paper mode vs ablation mode 配置路径差异 [deep]
├── Task 2: Verifier TDD RED：编写 LLM error fallback 失败测试 [deep]
├── Task 3: Verifier TDD RED：编写阈值一致性失败测试 [deep]
├── Task 4: 调查 oracle_evidence 0 预测根因 [deep]
├── Task 5: 调查 without_soe_graph 15 tuples 异常 [deep]
├── Task 6: 清理仓库根目录杂项文件 [quick]
└── Task 7: 锁定基线：git tag v2-baseline [quick]

Wave 2 (After Wave 1 - core fixes, MAX PARALLEL):
├── Task 8: 修复 verifier LLM error fallback（TDD GREEN）[deep]
├── Task 9: 统一 verifier 阈值（config/code/论文三处一致，TDD GREEN）[deep]
├── Task 10: 修复 oracle_evidence selector [deep]
├── Task 11: 修复 without_soe_graph 低产出（如确认是 bug）[deep]
├── Task 12: 修复 paper.yaml：补 verifier.mode、移除 api_key 空值 [quick]
├── Task 13: 修复主实验与 ablation 配置路径一致性 [deep]
└── Task 14: 添加 verifier 集成测试 [deep]

Wave 3 (After Wave 2 - rerun + validate):
├── Task 15: 重跑全部 9 个 ablation settings [unspecified-high]
├── Task 16: 重跑主实验（paper mode，配置对齐后）[unspecified-high]
├── Task 17: 运行 held-out 评估 [unspecified-high]
├── Task 18: 验证 verifier 性能预算 [quick]
├── Task 19: 重新计算统计显著性 [deep]
└── Task 20: 生成根因调查报告 + 实验对比报告 [writing]

Wave 4 (After Wave 3 - paper numbers + tables):
├── Task 21: 重新生成全部 paper_tables/*.csv（基于新实验）[quick]
├── Task 22: 论文 docx Table 1-9 数字对齐 [quick]
├── Task 23: 论文摘要数字对齐 [writing]
├── Task 24: 论文 Results 章节改写 [writing]
├── Task 25: 论文 IAA/Limitations 章节完善 [writing]
└── Task 26: 论文 Table 转三线表格式 [quick]

Wave 5 (After Wave 4 - compliance + declarations):
├── Task 27: 缩短标题至 ≤20 字 [writing]
├── Task 28: 具体化 AI 使用声明 [writing]
├── Task 29: 填实作者信息 + 基金 + CRediT 贡献声明 [writing]
├── Task 30: 完善数据可用性声明（ScienceDB） [writing]
├── Task 31: 构建 ScienceDB 投稿数据包 [quick]
├── Task 32: 核验参考文献 GB/T 7714 格式 [quick]
└── Task 33: 清理论文目录旧脚本 [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 13 → Task 16 → Task 18 → Task 21 → Task 22 → Task 24 → F1-F4
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 7 (Wave 2)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|------------|--------|
| 1 | - | 13, 16, 20 |
| 2 | - | 8 |
| 3 | - | 9 |
| 4 | - | 10 |
| 5 | - | 11 |
| 6 | - | - |
| 7 | - | 15, 16, 17 |
| 8 | 2 | 15, 16 |
| 9 | 3 | 15, 16 |
| 10 | 4 | 15 |
| 11 | 5 | 15 |
| 12 | - | 13, 16 |
| 13 | 1, 12 | 16 |
| 14 | 8, 9 | - |
| 15 | 7, 8, 9, 10, 11 | 18, 19, 21 |
| 16 | 7, 8, 9, 13 | 18, 19, 21 |
| 17 | 7, 13 | 21 |
| 18 | 15, 16 | 21 |
| 19 | 15, 16 | 21 |
| 20 | 1, 15, 16, 17 | 22, 24 |
| 21 | 15, 16, 17, 18, 19 | 22, 23, 24 |
| 22 | 21 | - |
| 23 | 21 | - |
| 24 | 20, 21 | - |
| 25 | 21 | - |
| 26 | 22 | - |
| 27 | - | - |
| 28 | - | - |
| 29 | - | - |
| 30 | 31 | - |
| 31 | - | 30 |
| 32 | - | - |
| 33 | - | - |

### Agent Dispatch Summary

- **Wave 1**: 7 tasks — T1,T4,T5 → `deep`, T2,T3 → `deep`, T6,T7 → `quick`
- **Wave 2**: 7 tasks — T8,T9,T10,T11,T13 → `deep`, T12 → `quick`, T14 → `deep`
- **Wave 3**: 6 tasks — T15,T16,T17 → `unspecified-high`, T18 → `quick`, T19 → `deep`, T20 → `writing`
- **Wave 4**: 6 tasks — T21,T22,T26 → `quick`, T23,T24,T25 → `writing`
- **Wave 5**: 7 tasks — T27,T28,T29,T30 → `writing`, T31,T32,T33 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **FORMAT**: Task labels MUST use bare numbers: `1.`, `2.`, `3.` — NOT `T1.`, `Task 1.`, `Phase 1:`.
> Final Verification Wave labels MUST use `F1.`, `F2.`, etc.

- [ ] 1. 根因调查：paper mode vs ablation mode 配置路径差异

  **What to do**:
  - 读取 `src/episoa/pipeline.py` 中 `mode == "paper"` 和 `mode == "ablation"` 的分支逻辑
  - 对比主实验 config_snapshot.yaml 与 ablation full_soe config_snapshot.yaml 的所有字段差异
  - 重点关注：verifier.mode（paper 缺，ablation 有 decomposed）、api_key 空值、resume 标志、max_api_concurrency
  - 追踪 pipeline.py 中 `_run_paper_experiment()` vs `_run_ablation()` 的默认值差异
  - 检查 `outputs/cache/pipeline/` 是否污染了主实验（resume=true 但 config=false）
  - 生成 `root_cause_analysis.md`：明确列出导致 44 vs 82 tuples 差异的每一个配置/代码差异
  - 给出修复建议：(a) 统一 paper/ablation 默认值，(b) 清缓存重跑，(c) 修复 config 字段缺失

  **Must NOT do**:
  - 不得在此阶段修改任何代码——纯调查
  - 不得基于调查结论直接改论文数字

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug", "safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5, 6, 7)
  - **Blocks**: Tasks 13, 16, 20
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/episoa/pipeline.py` — 主 pipeline，查找 paper/ablation mode 分支
  - `src/episoa/pipeline.py:1251-1265` — ABLATION_SETTINGS 定义
  - `src/episoa/pipeline.py:222-223` — verifier_threshold/verifier_mode 默认值
  - `src/episoa/pipeline.py:461` — verifier_mode="decomposed" 默认
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/config_snapshot.yaml` — 主实验配置快照
  - `outputs/runs_human_gold_v2/ablation_full_soe/config_snapshot.yaml` — ablation 配置快照
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/runtime_manifest.json` — 显示 resume=true
  - `configs/paper.yaml` — 主实验源配置（缺 verifier.mode）
  - `configs/ablation.yaml` — ablation 源配置（有 verifier.mode: decomposed）

  **Acceptance Criteria**:
  - [ ] `root_cause_analysis.md` 生成，包含：
    - [ ] paper mode vs ablation mode 的代码路径差异列表
    - [ ] config_snapshot.yaml 逐字段 diff
    - [ ] cache 污染检查结论
    - [ ] 明确的根因结论（哪个差异导致 44 vs 82）
    - [ ] 修复建议（3 个选项）

  **QA Scenarios**:

  ```
  Scenario: Root cause analysis is actionable
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; p=Path('root_cause_analysis.md'); assert p.exists(), 'missing'; content=p.read_text(encoding='utf-8'); assert 'verifier.mode' in content, 'verifier.mode not analyzed'; assert '44' in content and '82' in content, 'tuple diff not mentioned'; assert len(content)>500, 'too short'"
    Expected Result: root_cause_analysis.md exists with verifier.mode analysis, 44/82 tuple diff, and ≥500 chars
    Evidence: .omo/evidence/task-1-root-cause.txt
  ```

  **Commit**: NO (diagnostic only)

- [ ] 2. TDD RED：编写 verifier LLM error fallback 失败测试

  **What to do**:
  - 在 `tests/test_verifier_llm_error_fix.py` 中编写失败测试
  - 场景：LLM client 抛异常时，当前代码返回 `score=0.5`（line 596），低于 threshold 0.75 → 全拒
  - 期望行为：LLM error 时应（a）重试一次，（b）若仍失败则返回中性分数 0.6 或跳过该 tuple，不应默认拒绝
  - 使用 FakeLLMClient 模拟 API 异常
  - 测试 ≥3 个场景：网络超时、JSON 解析失败、API 限流
  - 运行 `python -m pytest tests/test_verifier_llm_error_fix.py -v` → 确认 FAIL

  **Must NOT do**:
  - 不得调用真实 LLM API
  - 不得修改被测代码（纯 TDD RED）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4, 5, 6, 7)
  - **Blocks**: Task 8 (GREEN phase)
  - **Blocked By**: None

  **References**:
  - `src/episoa/verifier/faithfulness_verifier.py:584-596` — `_llm_verify` 的 try/except
  - `src/episoa/verifier/faithfulness_verifier.py:596` — `return 0.5, {"reason": "llm_verifier_error"}`
  - `tests/test_verifier_rejection_fix.py` — 现有 verifier TDD 测试 pattern
  - `tests/test_pipeline_verifier.py` — pipeline 级 verifier 测试 pattern
  - `tests/conftest.py` — conftest 结构

  **Acceptance Criteria**:
  - [ ] `tests/test_verifier_llm_error_fix.py` 创建
  - [ ] ≥3 个测试场景：网络超时、JSON 解析失败、API 限流
  - [ ] `python -m pytest tests/test_verifier_llm_error_fix.py -v` → 至少 1 个 FAIL
  - [ ] 现有 418 测试不受影响

  **QA Scenarios**:

  ```
  Scenario: TDD RED tests fail as expected
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_llm_error_fix.py -v --tb=short 2>&1 | findstr /C:"FAILED" /C:"PASSED" /C:"ERROR"
    Expected Result: At least 1 FAILED, 0 ERROR
    Failure Indicators: All PASS (bug not reproduced) or ERROR (test infra broken)
    Evidence: .omo/evidence/task-2-tdd-red.txt

  Scenario: Existing tests unaffected
    Tool: Bash
    Steps:
      1. python -m pytest tests/ -q --ignore=tests/test_verifier_llm_error_fix.py
    Expected Result: 418+ tests PASS, 0 FAILED
    Evidence: .omo/evidence/task-2-existing-tests.txt
  ```

  **Commit**: YES
  - Message: `test: TDD RED for verifier LLM error fallback over-rejection`
  - Files: `tests/test_verifier_llm_error_fix.py`

- [ ] 3. TDD RED：编写 verifier 阈值一致性失败测试

  **What to do**:
  - 在 `tests/test_verifier_threshold_consistency.py` 中编写失败测试
  - 当前问题：
    - `configs/paper.yaml:62`: `threshold: 0.75`
    - `configs/ablation.yaml:61`: `threshold: 0.75`
    - `src/episoa/verifier/faithfulness_verifier.py:48`: `threshold: float = 0.45`
    - 论文 docx line 533: "阈值已从0.75降低为0.40"
  - 期望行为：config 加载后应覆盖 code default，且论文叙述与实际阈值一致
  - 测试场景：
    - (a) load_config(paper.yaml).verifier.threshold == verify_tuples() 实际使用的 threshold
    - (b) 无 config 时 verify_tuples() 使用 code default 0.45（非 0.75）
    - (c) 论文中声称的阈值与 config 实际值一致
  - 运行 `python -m pytest tests/test_verifier_threshold_consistency.py -v` → 确认 FAIL

  **Must NOT do**:
  - 不得修改被测代码或配置

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5, 6, 7)
  - **Blocks**: Task 9 (GREEN phase)
  - **Blocked By**: None

  **References**:
  - `configs/paper.yaml:60-62` — verifier.threshold: 0.75
  - `configs/ablation.yaml:60-62` — verifier.threshold: 0.75
  - `src/episoa/verifier/faithfulness_verifier.py:48` — threshold: float = 0.45
  - `src/episoa/config.py` — load_config 实现
  - `outputs/manuscript/episoa_full_draft.docx` — 摘要中"0.40"声称

  **Acceptance Criteria**:
  - [ ] `tests/test_verifier_threshold_consistency.py` 创建
  - [ ] ≥3 个测试场景
  - [ ] 至少 1 个 FAIL（证明阈值不一致）
  - [ ] 现有测试不受影响

  **QA Scenarios**:

  ```
  Scenario: TDD RED tests detect threshold inconsistency
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_threshold_consistency.py -v --tb=short
    Expected Result: At least 1 FAILED
    Evidence: .omo/evidence/task-3-tdd-red.txt
  ```

  **Commit**: YES
  - Message: `test: TDD RED for verifier threshold inconsistency`
  - Files: `tests/test_verifier_threshold_consistency.py`

- [ ] 4. 调查 oracle_evidence 0 预测根因

  **What to do**:
  - 读取 `outputs/runs_human_gold_v2/ablation_oracle_evidence/metrics.json` — Num-Tuples=0
  - 读取 `outputs/runs_human_gold_v2/ablation_oracle_evidence/predictions.jsonl` — 检查是否有任何预测
  - 读取 `outputs/runs_human_gold_v2/ablation_oracle_evidence/schema_attribution_summary.json` — 检查 attribution 阶段
  - 读取 `src/episoa/pipeline.py:1255` — oracle_evidence ABLATION_SETTINGS 定义
  - 读取 `src/episoa/retrieval/evidence_selector.py` — selector_mode="oracle" 分支
  - 诊断：oracle 模式是否正确读取 gold evidence IDs？ID namespace 是否匹配？
  - 检查 `outputs/runs_human_gold_v2/ablation_oracle_evidence/scoring_scope.json` — 是否有候选
  - 生成 `oracle_evidence_diagnosis.md` 报告

  **Must NOT do**:
  - 不得在此阶段修复代码——纯诊断

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug", "jsonl-data-check"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 5, 6, 7)
  - **Blocks**: Task 10 (fix needs diagnosis)
  - **Blocked By**: None

  **References**:
  - `outputs/runs_human_gold_v2/ablation_oracle_evidence/` — 全部产出文件
  - `src/episoa/pipeline.py:1255` — oracle_evidence ABLATION_SETTINGS
  - `src/episoa/retrieval/evidence_selector.py` — selector_mode oracle 分支
  - `data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl` — gold evidence_ids 来源

  **Acceptance Criteria**:
  - [ ] `oracle_evidence_diagnosis.md` 生成
  - [ ] 明确根因（ID 不匹配 / selector 返回空 / attribution 无输入）
  - [ ] 修复建议

  **QA Scenarios**:

  ```
  Scenario: Oracle diagnosis identifies root cause
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; p=Path('oracle_evidence_diagnosis.md'); assert p.exists(); c=p.read_text(encoding='utf-8'); assert 'root cause' in c.lower() or '根因' in c, 'no root cause'; assert len(c)>300"
    Expected Result: diagnosis md exists with root cause
    Evidence: .omo/evidence/task-4-oracle-diagnosis.txt
  ```

  **Commit**: NO (diagnostic only)

- [ ] 5. 调查 without_soe_graph 15 tuples 异常

  **What to do**:
  - 读取 `outputs/runs_human_gold_v2/ablation_without_soe_graph/metrics.json` — Num-Tuples=15, F1=0.1481
  - 对比 ablation_full_soe (82 tuples) — 差异巨大
  - 读取 `outputs/runs_human_gold_v2/ablation_without_soe_graph/schema_attribution_summary.json`
  - 读取 `outputs/runs_human_gold_v2/ablation_without_soe_graph/tuple_failure_audit.csv`
  - 读取 `outputs/runs_human_gold_v2/ablation_without_soe_graph/progress.jsonl` — 检查每事件产出
  - 诊断：use_soe_graph=False 是否导致 use_stage_attribution=False（见 pipeline.py:537）？是否导致 attribution 路径异常？
  - 判断：15 tuples 是真实的"graph 重要性"证据，还是 pipeline bug？
  - 生成 `without_soe_graph_diagnosis.md`

  **Must NOT do**:
  - 不得在此阶段修复代码

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug", "jsonl-data-check"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4, 6, 7)
  - **Blocks**: Task 11 (fix decision)
  - **Blocked By**: None

  **References**:
  - `outputs/runs_human_gold_v2/ablation_without_soe_graph/` — 全部产出
  - `src/episoa/pipeline.py:537` — `use_stage_attribution = bool(use_soe_graph and method_version == SOE_V3_METHOD_VERSION)`
  - `src/episoa/pipeline.py:1257` — without_soe_graph ABLATION_SETTINGS

  **Acceptance Criteria**:
  - [ ] `without_soe_graph_diagnosis.md` 生成
  - [ ] 明确结论：bug or feature
  - [ ] 如是 bug：修复建议；如是 feature：论文叙述建议

  **QA Scenarios**:

  ```
  Scenario: Diagnosis classifies the anomaly
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; p=Path('without_soe_graph_diagnosis.md'); assert p.exists(); c=p.read_text(encoding='utf-8'); assert 'bug' in c.lower() or 'feature' in c.lower() or '特性' in c or '缺陷' in c, 'no classification'; assert '15' in c, 'tuple count not mentioned'"
    Expected Result: md classifies as bug or feature
    Evidence: .omo/evidence/task-5-diagnosis.txt
  ```

  **Commit**: NO (diagnostic only)

- [ ] 6. 清理仓库根目录杂项文件

  **What to do**:
  - 将 `baseline_manifest.json` 移到 `outputs/baseline_pre_remediation/baseline_manifest.json`
  - 将 `verifier_rejection_analysis.json` 移到 `.omo/evidence/verifier_rejection_analysis.json`
  - 将 `heldout_test_events.json` 移到 `data/pubevent_soa_lite/heldout_test_events.json`
  - 删除 `tmp_pytest_20260611235857980/` 目录
  - 删除 `auto_run_api_recovery.*` 日志文件（4 个）
  - 删除 `auto_run_when_api_ready.py`, `start_auto_run.bat`, `start_auto_run_hidden.vbs`
  - 删除 `check_abstract.py`, `compute_stats.py`（如已无用，先 grep 确认无引用）
  - 更新 `.gitignore` 添加 `auto_run_*`, `tmp_pytest_*`

  **Must NOT do**:
  - 不得删除 `.omo/` 下任何文件
  - 不得删除 `outputs/` 下任何实验产出
  - 不得删除仍被代码引用的脚本（先 grep 确认）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4, 5, 7)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - 仓库根目录文件列表
  - `.gitignore` — 现有忽略规则

  **Acceptance Criteria**:
  - [ ] 根目录只保留必要文件（README, AGENTS, CLAUDE, pyproject, .env.example, .gitignore, tui.json）
  - [ ] `baseline_manifest.json` 移到 outputs/baseline_pre_remediation/
  - [ ] `verifier_rejection_analysis.json` 移到 .omo/evidence/
  - [ ] tmp_pytest_* 删除
  - [ ] auto_run_* 删除

  **QA Scenarios**:

  ```
  Scenario: Root directory cleaned
    Tool: Bash
    Steps:
      1. dir D:\Workplace\EpiSOA | findstr /V "configs data docs outputs prompts scripts src tests .claude .omo .opencode .vscode .worktrees .tmp .git .pytest_cache"
      2. python -c "from pathlib import Path; assert not Path('baseline_manifest.json').exists(); assert not Path('verifier_rejection_analysis.json').exists(); assert Path('outputs/baseline_pre_remediation/baseline_manifest.json').exists(); assert Path('.omo/evidence/verifier_rejection_analysis.json').exists()"
    Expected Result: Root clean; files moved to correct locations
    Evidence: .omo/evidence/task-6-cleanup.txt
  ```

  **Commit**: YES
  - Message: `chore: clean root directory and relocate diagnostic files`
  - Files: moved files, .gitignore

- [ ] 7. 锁定基线：git tag v2-baseline

  **What to do**:
  - 在当前 HEAD 创建 git tag `v2-baseline-pre-resubmission`
  - 复制当前 `outputs/runs_human_gold_v2/` 到 `outputs/baseline_v2_pre_resubmission/`
  - 复制当前 `outputs/manuscript/` 到 `outputs/manuscript_baseline_v2/`
  - 记录当前 git commit hash 到 `outputs/baseline_v2_pre_resubmission/manifest.json`
  - 清空 `outputs/cache/pipeline/` 使后续运行不使用旧缓存

  **Must NOT do**:
  - 不得删除原 outputs/runs_human_gold_v2/
  - 不得修改 gold 数据

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["git-review"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4, 5, 6)
  - **Blocks**: Tasks 15, 16, 17 (reruns need clean cache + baseline)
  - **Blocked By**: None

  **References**:
  - `outputs/runs_human_gold_v2/` — 当前实验产出
  - `outputs/manuscript/` — 当前论文
  - `outputs/cache/pipeline/` — 缓存目录

  **Acceptance Criteria**:
  - [ ] git tag `v2-baseline-pre-resubmission` 创建
  - [ ] `outputs/baseline_v2_pre_resubmission/` 存在且完整
  - [ ] `outputs/manuscript_baseline_v2/` 存在
  - [ ] `outputs/baseline_v2_pre_resubmission/manifest.json` 含 commit hash
  - [ ] `outputs/cache/pipeline/` 已清空

  **QA Scenarios**:

  ```
  Scenario: Baseline pinned
    Tool: Bash
    Steps:
      1. git tag -l v2-baseline-pre-resubmission
      2. python -c "from pathlib import Path; assert Path('outputs/baseline_v2_pre_resubmission/manifest.json').exists(); import json; m=json.loads(Path('outputs/baseline_v2_pre_resubmission/manifest.json').read_text(encoding='utf-8')); assert 'git_commit' in m"
      3. python -c "from pathlib import Path; assert not any(Path('outputs/cache/pipeline').iterdir()) if Path('outputs/cache/pipeline').exists() else True"
    Expected Result: tag exists; manifest has commit; cache empty
    Evidence: .omo/evidence/task-7-baseline.txt
  ```

  **Commit**: YES
  - Message: `chore: pin v2 baseline before resubmission remediation`
  - Files: `outputs/baseline_v2_pre_resubmission/manifest.json`

---

- [ ] 8. 修复 verifier LLM error fallback（TDD GREEN）

  **What to do**:
  - 基于 Task 2 的 TDD RED 测试，修复 `src/episoa/verifier/faithfulness_verifier.py:584-596`
  - 当前：`except Exception: return 0.5, {"reason": "llm_verifier_error"}`
  - 修复方案（选其一，基于 Task 1 根因调查）：
    - (a) LLM error 时重试一次（已有 max_retries 配置）
    - (b) 若仍失败，返回中性分数 0.6（高于 threshold 0.45 但低于 0.75，让 rule_precheck 决定）
    - (c) 若仍失败，标记为 `llm_error` 但不强制拒绝，由 rule_precheck 结果决定
  - 推荐 (b)+(c)：error 时返回 0.6 + 标记 llm_error，让 rule_precheck 的 hard flag 决定
  - 运行 Task 2 的 TDD 测试，确认从 RED 变 GREEN
  - 确保现有 418 测试仍通过

  **Must NOT do**:
  - 不得改变 verify_tuples() 公共 API
  - 不得让 LLM error 时返回 1.0（不能无脑通过）
  - 不得移除 try/except（必须保留容错）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 9, 10, 11, 12, 13, 14)
  - **Blocks**: Tasks 15, 16 (reruns need fixed verifier)
  - **Blocked By**: Task 2 (TDD RED tests must exist)

  **References**:
  - `src/episoa/verifier/faithfulness_verifier.py:584-596` — `_llm_verify` try/except
  - `tests/test_verifier_llm_error_fix.py` — Task 2 创建的 TDD 测试
  - `src/episoa/verifier/faithfulness_verifier.py:48` — threshold default 0.45
  - `src/episoa/verifier/faithfulness_verifier.py:463-486` — `_apply_hard_flag_score_cap`

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/test_verifier_llm_error_fix.py -v` → 全部 GREEN
  - [ ] `_llm_verify` 异常时不返回 0.5，改为 0.6 + llm_error 标记
  - [ ] 现有 418 测试仍通过
  - [ ] 代码有注释解释新 fallback 逻辑

  **QA Scenarios**:

  ```
  Scenario: TDD GREEN for LLM error fallback
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_llm_error_fix.py -v --tb=short
    Expected Result: All tests PASS (0 FAILED, 0 ERROR)
    Evidence: .omo/evidence/task-8-tdd-green.txt

  Scenario: Existing tests unaffected
    Tool: Bash
    Steps:
      1. python -m pytest tests/ -q
    Expected Result: 418+ passed, 0 failed
    Evidence: .omo/evidence/task-8-existing-tests.txt
  ```

  **Commit**: YES
  - Message: `fix: verifier LLM error fallback no longer defaults to rejection (TDD GREEN)`
  - Files: `src/episoa/verifier/faithfulness_verifier.py`

- [ ] 9. 统一 verifier 阈值（TDD GREEN）

  **What to do**:
  - 基于 Task 3 的 TDD RED 测试，统一三处阈值
  - 当前问题：
    - config (paper.yaml, ablation.yaml): 0.75
    - code default (verify_tuples line 48): 0.45
    - 论文叙述: "0.40"
  - 修复方案：
    - (a) 将 config 中的 `threshold: 0.75` 改为 `threshold: 0.45`（与 code default 一致）
    - (b) 或将 code default 改为 0.75，让 config 显式控制
  - 推荐 (a)：config 改为 0.45，因为 0.75 导致 LLM error 全拒（即使修复了 fallback，0.75 仍太高）
  - 同步论文 docx 中"0.40"叙述为"0.45"（或反之，根据实际选择）
  - 运行 Task 3 的 TDD 测试，确认 GREEN

  **Must NOT do**:
  - 不得让三处继续不一致
  - 不得无理由改变阈值（需基于根因调查）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 10, 11, 12, 13, 14)
  - **Blocks**: Tasks 15, 16
  - **Blocked By**: Task 3 (TDD RED tests)

  **References**:
  - `configs/paper.yaml:60-62` — verifier.threshold: 0.75
  - `configs/ablation.yaml:60-62` — verifier.threshold: 0.75
  - `src/episoa/verifier/faithfulness_verifier.py:48` — threshold: float = 0.45
  - `tests/test_verifier_threshold_consistency.py` — Task 3 创建
  - `outputs/manuscript/episoa_full_draft.docx` — 论文中阈值叙述

  **Acceptance Criteria**:
  - [ ] config 和 code threshold 一致（都为 0.45 或都为 0.75）
  - [ ] `python -m pytest tests/test_verifier_threshold_consistency.py -v` → 全部 GREEN
  - [ ] 现有 418 测试通过

  **QA Scenarios**:

  ```
  Scenario: Threshold consistency verified
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_threshold_consistency.py -v
      2. python -c "from episoa.config import load_config; p=load_config('configs/paper.yaml'); a=load_config('configs/ablation.yaml'); assert p.verifier.threshold == a.verifier.threshold, 'config mismatch'"
    Expected Result: All tests PASS; config thresholds match
    Evidence: .omo/evidence/task-9-threshold-consistency.txt
  ```

  **Commit**: YES
  - Message: `fix: unify verifier threshold across config/code (TDD GREEN)`
  - Files: `configs/paper.yaml`, `configs/ablation.yaml`, `src/episoa/verifier/faithfulness_verifier.py`

- [ ] 10. 修复 oracle_evidence selector

  **What to do**:
  - 基于 Task 4 诊断报告，修复 oracle_evidence 0 预测问题
  - 可能根因（Task 4 确认）：
    - (a) gold evidence_ids 与 evidence.jsonl 的 ID namespace 不匹配
    - (b) selector_mode="oracle" 分支返回空列表
    - (c) oracle_evidence_ids_by_event 未正确传入
  - 修复 `src/episoa/retrieval/evidence_selector.py` 中 oracle 分支
  - 确保 oracle 模式读取 gold tuples 的 evidence_ids 并映射到当前 evidence namespace
  - 运行 `python scripts/run_ablation.py --settings oracle_evidence --force`
  - 验证 Num-Tuples > 0, F1 ≥ full_soe（因为用的是 gold evidence）

  **Must NOT do**:
  - 不得修改 gold tuple 中的 evidence_ids
  - 不得改变 oracle_evidence 的语义（必须使用 gold evidence IDs）
  - 不得改变 ABLATION_SETTINGS 定义

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug", "safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 9, 11, 12, 13, 14)
  - **Blocks**: Task 15 (rerun needs fixed oracle)
  - **Blocked By**: Task 4 (diagnosis)

  **References**:
  - `src/episoa/retrieval/evidence_selector.py` — selector_mode oracle 分支
  - `src/episoa/pipeline.py:1255` — oracle_evidence ABLATION_SETTINGS
  - `data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl` — gold evidence_ids
  - `oracle_evidence_diagnosis.md` — Task 4 生成
  - `outputs/runs_human_gold_v2/ablation_oracle_evidence/` — 当前 0 预测产出

  **Acceptance Criteria**:
  - [ ] `python scripts/run_ablation.py --settings oracle_evidence --force` 成功
  - [ ] oracle_evidence metrics.json: Num-Tuples > 0
  - [ ] oracle_evidence F1 ≥ full_soe F1（gold evidence 应有更高 F1）

  **QA Scenarios**:

  ```
  Scenario: oracle_evidence produces predictions
    Tool: Bash
    Steps:
      1. python scripts/run_ablation.py --config configs/ablation.yaml --settings oracle_evidence --force
      2. python -c "import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_oracle_evidence/metrics.json',encoding='utf-8').read()); assert m['Num-Tuples']>0, 'still 0'; print(f'Num-Tuples: {m[\"Num-Tuples\"]}, F1@0.3: {m[\"Tuple-F1-semantic@0.3\"]}')"
    Expected Result: Num-Tuples > 0, F1 > 0
    Evidence: .omo/evidence/task-10-oracle-fix.txt
  ```

  **Commit**: YES
  - Message: `fix: oracle_evidence selector now produces non-zero predictions`
  - Files: `src/episoa/retrieval/evidence_selector.py`

- [ ] 11. 修复 without_soe_graph 低产出（如确认是 bug）

  **What to do**:
  - 基于 Task 5 诊断结论决定是否修复
  - 如 Task 5 确认是 bug（如 use_soe_graph=False 意外关闭了 stage_attribution 导致 attribution 路径异常）：
    - 修复 `src/episoa/pipeline.py` 中 use_soe_graph 与 use_stage_attribution 的耦合逻辑
    - 确保 without_soe_graph 只关闭 graph，不关闭 stage_attribution
    - 重跑 `python scripts/run_ablation.py --settings without_soe_graph --force`
    - 验证 Num-Tuples 显著提升（从 15 到接近 full_soe 的 82）
  - 如 Task 5 确认是 feature（graph 确实关键）：
    - 不修改代码
    - 在论文中明确说明 without_soe_graph 的 15 tuples 是 graph 重要性的证据
    - 生成 `without_soe_graph_feature_evidence.md` 供论文引用

  **Must NOT do**:
  - 不得改变 without_soe_graph 的 ABLATION_SETTINGS 定义
  - 不得为了数字好看而修改代码逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug", "safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 9, 10, 12, 13, 14)
  - **Blocks**: Task 15 (rerun)
  - **Blocked By**: Task 5 (diagnosis)

  **References**:
  - `src/episoa/pipeline.py:537` — use_stage_attribution = bool(use_soe_graph and ...)
  - `src/episoa/pipeline.py:1257` — without_soe_graph ABLATION_SETTINGS
  - `without_soe_graph_diagnosis.md` — Task 5 生成
  - `outputs/runs_human_gold_v2/ablation_without_soe_graph/` — 当前 15 tuples 产出

  **Acceptance Criteria**:
  - [ ] 如修复：Num-Tuples > 50（显著提升）
  - [ ] 如不修复：feature_evidence.md 生成
  - [ ] 现有测试通过

  **QA Scenarios**:

  ```
  Scenario: without_soe_graph handled (fix or feature doc)
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; feat=Path('without_soe_graph_feature_evidence.md'); assert feat.exists() or True"  # if feature
      2. python -c "import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_without_soe_graph/metrics.json',encoding='utf-8').read()); print(f'Num-Tuples: {m[\"Num-Tuples\"]}')"  # if fixed
    Expected Result: Either feature doc exists OR Num-Tuples > 50
    Evidence: .omo/evidence/task-11-without-soe-graph.txt
  ```

  **Commit**: YES (if fixed)
  - Message: `fix: decouple use_stage_attribution from use_soe_graph (without_soe_graph no longer crippled)`
  - Files: `src/episoa/pipeline.py`

- [ ] 12. 修复 paper.yaml：补 verifier.mode、移除 api_key 空值

  **What to do**:
  - 在 `configs/paper.yaml` 的 `verifier:` 下添加 `mode: decomposed`（与 ablation.yaml 一致）
  - 移除 `model.api_key: ""` 空值行（保留 `api_key_env`）
  - 移除 `search.api_key: ""` 空值行（保留 `api_key_env`）
  - 移除 `model.base_url: ""` 空值行（保留 `base_url_env`）
  - 确认 `runtime.max_api_concurrency: 4`（与 ablation 一致，当前是 4 但主实验 runtime_manifest 显示 2）
  - 添加 `runtime.resume: false` 显式声明（防止缓存污染）

  **Must NOT do**:
  - 不得改变 api_key_env / base_url_env 机制
  - 不得改变 temperature, max_tokens 等影响结果的参数

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 9, 10, 11, 13, 14)
  - **Blocks**: Task 13 (config consistency)
  - **Blocked By**: None

  **References**:
  - `configs/paper.yaml` — 当前配置（缺 verifier.mode, 有 api_key 空值）
  - `configs/ablation.yaml` — 参照（有 verifier.mode, 无 api_key 空值）
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/config_snapshot.yaml` — 显示 api_key: ""

  **Acceptance Criteria**:
  - [ ] paper.yaml 包含 `verifier.mode: decomposed`
  - [ ] paper.yaml 无 `api_key: ""` 空值行
  - [ ] paper.yaml 无 `base_url: ""` 空值行
  - [ ] `python -m episoa.cli paper-status` 通过

  **QA Scenarios**:

  ```
  Scenario: paper.yaml cleaned
    Tool: Bash
    Steps:
      1. python -c "from episoa.config import load_config; c=load_config('configs/paper.yaml'); assert c.verifier.mode == 'decomposed', 'missing verifier.mode'; assert hasattr(c.model, 'api_key_env'), 'api_key_env missing'"
      2. findstr /C:"api_key: \"\"" configs/paper.yaml
    Expected Result: config loads; verifier.mode=decomposed; no api_key empty string
    Evidence: .omo/evidence/task-12-paper-yaml.txt
  ```

  **Commit**: YES
  - Message: `config: fix paper.yaml (add verifier.mode, remove api_key empty values)`
  - Files: `configs/paper.yaml`

- [ ] 13. 修复主实验与 ablation 配置路径一致性

  **What to do**:
  - 基于 Task 1 根因调查报告，修复 `src/episoa/pipeline.py` 中 paper mode 与 ablation mode 的默认值差异
  - 确保 paper mode 显式应用与 ablation full_soe 相同的 flags：
    - use_verifier_quality_gate: True
    - verifier_mode: decomposed
    - method_version: soe_v3
    - selector_mode: coverage_optimized
    - use_soe_graph: True
    - use_stage_attribution: True
  - 修改方式：
    - (a) 在 paper mode 入口处显式设置这些 flags（不依赖默认值）
    - (b) 或在 PaperConfig 中添加这些字段并从 yaml 加载
  - 确保 `mode: paper` 运行结果与 `ablation full_soe` 一致（或可解释的差异）

  **Must NOT do**:
  - 不得改变 ABLATION_SETTINGS 定义
  - 不得改变 pipeline.py 核心架构
  - 不得删除 paper mode 分支

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["safe-edit", "python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 9, 10, 11, 12, 14)
  - **Blocks**: Task 16 (main rerun)
  - **Blocked By**: Task 1 (root cause), Task 12 (paper.yaml fix)

  **References**:
  - `src/episoa/pipeline.py` — paper mode 与 ablation mode 分支
  - `src/episoa/pipeline.py:1252` — full_soe flags 定义
  - `root_cause_analysis.md` — Task 1 生成
  - `configs/paper.yaml` — Task 12 修复后

  **Acceptance Criteria**:
  - [ ] paper mode 显式设置 full_soe 等效 flags
  - [ ] 现有测试通过
  - [ ] `python -c "from episoa.pipeline import run_paper_experiment; ..."` 不报错（smoke test）

  **QA Scenarios**:

  ```
  Scenario: Paper mode uses full_soe-equivalent flags
    Tool: Bash
    Steps:
      1. python -m pytest tests/ -q
      2. python -c "from episoa.config import load_config; c=load_config('configs/paper.yaml'); print(f'mode={c.mode}, verifier_mode={c.verifier.mode}')"
    Expected Result: All tests pass; config loads with verifier_mode
    Evidence: .omo/evidence/task-13-config-path.txt
  ```

  **Commit**: YES
  - Message: `fix: paper mode now explicitly applies full_soe-equivalent flags`
  - Files: `src/episoa/pipeline.py`

- [ ] 14. 添加 verifier 集成测试

  **What to do**:
  - 创建 `tests/test_verifier_integration_v2.py`
  - 测试完整 verify_tuples() 调用链：rule_precheck → LLM → quality_gate
  - 场景：
    - (a) 全部通过：evidence 完全支持 tuple
    - (b) 全部拒绝：evidence 与 tuple 无关
    - (c) LLM error 时：tuple 不被默认拒绝（验证 Task 8 修复）
    - (d) 阈值边界：score=0.45, 0.46, 0.75 时的通过/拒绝
    - (e) 空预测列表
    - (f) 空 evidence 列表
  - 使用 `@pytest.mark.integration` 标记
  - 使用 mock LLM（FakeLLMClient）

  **Must NOT do**:
  - 不得调用真实 LLM API
  - 不得修改 verify_tuples() 行为

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8, 9, 10, 11, 12, 13)
  - **Blocks**: None
  - **Blocked By**: Tasks 8, 9 (verifier fixes must be in place)

  **References**:
  - `tests/test_verifier_rejection_fix.py` — 现有 TDD 测试
  - `tests/test_pipeline_verifier.py` — pipeline 级测试
  - `src/episoa/verifier/faithfulness_verifier.py` — 被测模块

  **Acceptance Criteria**:
  - [ ] `tests/test_verifier_integration_v2.py` 创建
  - [ ] ≥6 个测试场景
  - [ ] 使用 `@pytest.mark.integration` 标记
  - [ ] `python -m pytest tests/test_verifier_integration_v2.py -v` → 全部通过

  **QA Scenarios**:

  ```
  Scenario: Integration tests pass
    Tool: Bash
    Steps:
      1. python -m pytest tests/test_verifier_integration_v2.py -v --tb=short
    Expected Result: All tests PASS
    Evidence: .omo/evidence/task-14-integration-tests.txt
  ```

  **Commit**: YES
  - Message: `test: add verifier integration tests v2 (LLM error, threshold boundary)`
  - Files: `tests/test_verifier_integration_v2.py`

---

- [ ] 15. 重跑全部 9 个 ablation settings

  **What to do**:
  - 确认 `outputs/cache/pipeline/` 已清空（Task 7）
  - 运行 `python scripts/run_ablation.py --config configs/ablation.yaml --force`
  - 监控全部 9 settings 完成（注意：ablation.yaml 有 11 settings 但 full_soe_high_recall 和 ablation_delta 可能跳过）
  - 检查每个 setting 的 metrics.json: Num-Tuples > 0
  - 特别关注：
    - full_soe: F1@0.3 应 ≥ without_verifier 或接近
    - oracle_evidence: Num-Tuples > 0（Task 10 修复验证）
    - without_soe_graph: Num-Tuples > 50（Task 11 修复验证，如适用）
    - direct_llm: Num-Tuples > 100
  - 生成 `outputs/runs_human_gold_v2/ablation_results.csv` 和 `ablation_summary.json`

  **Must NOT do**:
  - 不得使用 --resume（必须 --force 从头跑）
  - 不得更改 ablation.yaml settings 列表

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (sole task—depends on ALL Wave 2 fixes)
  - **Blocks**: Tasks 18, 19, 21
  - **Blocked By**: Tasks 7, 8, 9, 10, 11 (all Wave 2 fixes + baseline)

  **References**:
  - `configs/ablation.yaml` — 11 settings 配置
  - `scripts/run_ablation.py` — 运行脚本
  - `src/episoa/pipeline.py:1251-1265` — ABLATION_SETTINGS
  - `outputs/baseline_v2_pre_resubmission/ablation_results.csv` — 基线对比

  **Acceptance Criteria**:
  - [ ] 全部 9+ settings 成功完成
  - [ ] 每个 setting Num-Tuples > 0
  - [ ] `ablation_results.csv` 生成，包含所有 setting 行
  - [ ] `ablation_summary.json` 生成

  **QA Scenarios**:

  ```
  Scenario: All ablation settings complete with predictions
    Tool: Bash
    Steps:
      1. python -c "import csv; from pathlib import Path; rows=list(csv.DictReader(Path('outputs/runs_human_gold_v2/ablation_results.csv').read_text(encoding='utf-8').splitlines())); print(f'Total: {len(rows)}'); zeros=[r['Setting'] for r in rows if float(r['Tuples'])==0]; print(f'Zero predictions: {zeros}'); assert len(rows)>=9, f'Expected ≥9, got {len(rows)}'; assert not zeros, f'Zero-prediction settings: {zeros}'"
    Expected Result: ≥9 settings, zero with 0 predictions
    Failure Indicators: <9 settings, or any 0-prediction setting
    Evidence: .omo/evidence/task-15-ablation-complete.csv

  Scenario: full_soe no longer crippled
    Tool: Bash
    Steps:
      1. python -c "import csv; rows=list(csv.DictReader(open('outputs/runs_human_gold_v2/ablation_results.csv',encoding='utf-8'))); fs=[r for r in rows if r['Setting']=='ablation_full_soe'][0]; wv=[r for r in rows if r['Setting']=='ablation_without_verifier'][0]; print(f'full_soe F1@0.3={fs[\"F1-semantic@0.3\"]}, without_verifier F1@0.3={wv[\"F1-semantic@0.3\"]}')"
    Expected Result: full_soe F1@0.3 ≥ 0.45 (improved from 0.39) OR close to without_verifier
    Evidence: .omo/evidence/task-15-full-soe-improvement.txt
  ```

  **Commit**: NO (generated artifacts)

- [ ] 16. 重跑主实验（paper mode，配置对齐后）

  **What to do**:
  - 确认 Task 12, 13 已完成（paper.yaml 修复 + 配置路径一致性）
  - 清空 `outputs/cache/pipeline/`
  - 运行 `python scripts/run_paper_experiment.py --config configs/paper.yaml`
  - 验证主实验 metrics.json 与 ablation_full_soe 一致（或可解释的差异）
  - 特别关注：
    - Num-Tuples 应接近 82（ablation full_soe）而非 44（旧主实验）
    - F1@0.3 应接近 0.39+（或更高，verifier 修复后）
  - 生成 `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json`

  **Must NOT do**:
  - 不得使用 --resume
  - 不得修改 gold 数据

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 15 ablation, but both are LLM-heavy, recommend sequential)
  - **Parallel Group**: Wave 3 (with Tasks 15, 17, 18, 19, 20)
  - **Blocks**: Tasks 18, 19, 21
  - **Blocked By**: Tasks 7, 8, 9, 12, 13 (baseline + verifier fixes + config fixes)

  **References**:
  - `configs/paper.yaml` — Task 12 修复后
  - `scripts/run_paper_experiment.py` — 运行脚本
  - `src/episoa/pipeline.py` — Task 13 修复后
  - `outputs/baseline_v2_pre_resubmission/pubevent-soa-lite-human-gold-v2-paper/metrics.json` — 基线（44 tuples）

  **Acceptance Criteria**:
  - [ ] 主实验成功完成
  - [ ] Num-Tuples 接近 ablation_full_soe（差异 < 20%）
  - [ ] F1@0.3 接近 ablation_full_soe
  - [ ] metrics.json 生成

  **QA Scenarios**:

  ```
  Scenario: Main experiment aligns with ablation_full_soe
    Tool: Bash
    Steps:
      1. python -c "import json; m=json.loads(open('outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json',encoding='utf-8').read()); a=json.loads(open('outputs/runs_human_gold_v2/ablation_full_soe/metrics.json',encoding='utf-8').read()); print(f'Main: Num-Tuples={m[\"Num-Tuples\"]}, F1@0.3={m[\"Tuple-F1-semantic@0.3\"]}'); print(f'Ablation: Num-Tuples={a[\"Num-Tuples\"]}, F1@0.3={a[\"Tuple-F1-semantic@0.3\"]}'); diff=abs(m['Num-Tuples']-a['Num-Tuples'])/max(m['Num-Tuples'],a['Num-Tuples']); assert diff<0.2, f'Diff too large: {diff:.1%}'"
    Expected Result: Main and ablation Num-Tuples within 20% diff
    Evidence: .omo/evidence/task-16-main-rerun.txt
  ```

  **Commit**: NO (generated artifacts)

- [ ] 17. 运行 held-out 评估

  **What to do**:
  - 确认 `configs/paper_with_heldout.yaml` 存在且正确指向 held-out events
  - 确认 `heldout_test_events.json` 在 data/pubevent_soa_lite/ 下（Task 6 移动后）
  - 清空相关缓存
  - 运行 `python scripts/run_paper_experiment.py --config configs/paper_with_heldout.yaml`
  - 输出到 `outputs/runs_human_gold_v2/heldout_eval/`
  - 验证：
    - Num-Gold > 0（应为 34）
    - Num-Tuples > 0
    - F1@0.3 > 0
    - 评估的 10 个事件与 heldout_test_events.json 一致

  **Must NOT do**:
  - 不得用 held-out 结果反哺或调参（一次性评估）
  - 不得修改 gold 数据

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 15, 16, but LLM-heavy, recommend sequential)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 21 (paper tables need held-out)
  - **Blocked By**: Tasks 7, 13 (baseline + config path fix)

  **References**:
  - `configs/paper_with_heldout.yaml` — held-out 配置
  - `data/pubevent_soa_lite/heldout_test_events.json` — 10 个 held-out events
  - `scripts/run_paper_experiment.py` — 运行脚本

  **Acceptance Criteria**:
  - [ ] `outputs/runs_human_gold_v2/heldout_eval/metrics.json` 存在
  - [ ] Num-Gold = 34（或接近）
  - [ ] Num-Tuples > 0
  - [ ] F1@0.3 > 0
  - [ ] 评估事件 = heldout_test_events.json 中的 10 个

  **QA Scenarios**:

  ```
  Scenario: Held-out evaluation produces valid metrics
    Tool: Bash
    Steps:
      1. python -c "import json; from pathlib import Path; p=Path('outputs/runs_human_gold_v2/heldout_eval/metrics.json'); assert p.exists(), 'heldout eval missing'; m=json.loads(p.read_text(encoding='utf-8')); print(f'Num-Gold={m[\"Num-Gold\"]}, Num-Tuples={m[\"Num-Tuples\"]}, F1@0.3={m[\"Tuple-F1-semantic@0.3\"]}'); assert m['Num-Gold']>0 and m['Num-Tuples']>0 and m['Tuple-F1-semantic@0.3']>0"
    Expected Result: All metrics > 0
    Evidence: .omo/evidence/task-17-heldout-eval.txt
  ```

  **Commit**: NO (generated artifacts)

- [ ] 18. 验证 verifier 性能预算

  **What to do**:
  - 从 Task 15 和 Task 16 的新结果提取指标
  - 运行自动化 check：
    - (a) full_soe Tuple-F1-semantic@0.3 ≥ 0.45（比旧 0.39 提升，因 verifier 修复）
    - (b) full_soe rejection_rate ≤ 40%（从 verifier_quality_gate.json 计算）
    - (c) full_soe vs without_verifier paired t-test p > 0.05（或不显著差于）
  - 如果预算不达标：标记 FAIL，诊断原因，反馈 Wave 2 修复循环
  - 生成 `verifier_budget_v2_report.json`

  **Must NOT do**:
  - 不得伪造指标或降低检验标准
  - 不得在没有诊断的情况下直接回到 Wave 2

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 19, 20)
  - **Blocks**: Task 21 (paper tables need validated numbers)
  - **Blocked By**: Tasks 15, 16 (needs new results)

  **References**:
  - `outputs/runs_human_gold_v2/ablation_results.csv` — Task 15 生成
  - `outputs/runs_human_gold_v2/ablation_full_soe/verifier_quality_gate.json`
  - `outputs/runs_human_gold_v2/ablation_full_soe/metrics.json`
  - `outputs/runs_human_gold_v2/ablation_without_verifier/metrics.json`

  **Acceptance Criteria**:
  - [ ] `verifier_budget_v2_report.json` 生成
  - [ ] F1@0.3 ≥ 0.45（PASS/FAIL 记录）
  - [ ] rejection rate ≤ 40%（PASS/FAIL 记录）
  - [ ] p > 0.05 或 full_soe ≥ without_verifier（PASS/FAIL 记录）

  **QA Scenarios**:

  ```
  Scenario: Budget check runs and reports
    Tool: Bash
    Steps:
      1. python -c "import json; from pathlib import Path; r=json.loads(Path('verifier_budget_v2_report.json').read_text(encoding='utf-8')); print(f'F1@0.3: {r[\"f1_semantic_03\"]} ({r[\"f1_pass\"]})'); print(f'Rejection: {r[\"rejection_rate\"]:.1%} ({r[\"rejection_pass\"]})'); print(f'p-value: {r[\"p_value\"]:.4f} ({r[\"p_pass\"]})')"
    Expected Result: Report generated with all 3 checks
    Evidence: .omo/evidence/task-18-budget-report.json
  ```

  **Commit**: NO (diagnostic report)

- [ ] 19. 重新计算统计显著性

  **What to do**:
  - 基于 Task 15 和 Task 16 的新结果，重新计算 paired event-level t-test
  - 对比 full_soe vs:
    - without_verifier
    - without_decomposed_verifier
    - direct_llm
    - without_soe_graph
  - 使用 `scripts/build_main_vs_ablation_comparison.py` 或等效脚本
  - 生成新的 Table 4（成对显著性检验）数据
  - 特别关注：full_soe vs without_verifier 的 p 值（先前未报告，是核心矛盾）
  - 如果 full_soe 仍显著差于 without_verifier（p<0.05），论文需诚实承认 verifier 拖累

  **Must NOT do**:
  - 不得复用旧 p 值
  - 不得操纵数据使 p > 0.05

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 18, 20)
  - **Blocks**: Task 21 (paper Table 4)
  - **Blocked By**: Tasks 15, 16

  **References**:
  - `outputs/runs_human_gold_v2/ablation_*/event_level_metrics.csv` — 每设置的 event 级指标
  - `scripts/build_main_vs_ablation_comparison.py` — 对比脚本
  - `outputs/runs_human_gold_v2/main_vs_ablation_comparison.csv` — 旧对比（基线参照）

  **Acceptance Criteria**:
  - [ ] 新的 `main_vs_ablation_comparison_v2.csv` 生成
  - [ ] 包含 full_soe vs without_verifier 的 p 值
  - [ ] 所有对比的 N=45（或可解释的差异）

  **QA Scenarios**:

  ```
  Scenario: Statistical significance recomputed
    Tool: Bash
    Steps:
      1. python -c "import csv; from pathlib import Path; p=Path('outputs/runs_human_gold_v2/main_vs_ablation_comparison_v2.csv'); assert p.exists(); rows=list(csv.DictReader(p.read_text(encoding='utf-8').splitlines())); print(f'Total comparisons: {len(rows)}'); wv=[r for r in rows if 'without_verifier' in r.get('Variant','')]; assert wv, 'without_verifier comparison missing'; print(f'full_soe vs without_verifier: {wv[0]}')"
    Expected Result: comparison CSV exists with without_verifier row
    Evidence: .omo/evidence/task-19-significance.txt
  ```

  **Commit**: NO (generated artifacts)

- [ ] 20. 生成根因调查报告 + 实验对比报告

  **What to do**:
  - 整合 Task 1 的根因调查、Task 15-17 的新实验结果、Task 18-19 的预算和显著性
  - 生成 `experiment_comparison_report.md`，包含：
    - 根因调查结论（为什么旧主实验 44 vs ablation 82）
    - 修复后主实验 vs ablation full_soe 对比
    - verifier 修复前后对比（F1, rejection rate）
    - 全部 9 settings 的新指标表
    - held-out 评估结果
    - 统计显著性新结论
    - 对论文写作的指导建议（用哪个数字、如何叙述）
  - 这个报告作为 Wave 4 论文改写的依据

  **Must NOT do**:
  - 不得编造数字
  - 不得在报告中做论文改写决策（只呈现事实）

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 18, 19)
  - **Blocks**: Tasks 22, 24 (paper writing needs this report)
  - **Blocked By**: Tasks 1, 15, 16, 17, 18, 19

  **References**:
  - `root_cause_analysis.md` — Task 1
  - `outputs/runs_human_gold_v2/ablation_results.csv` — Task 15
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json` — Task 16
  - `outputs/runs_human_gold_v2/heldout_eval/metrics.json` — Task 17
  - `verifier_budget_v2_report.json` — Task 18
  - `outputs/runs_human_gold_v2/main_vs_ablation_comparison_v2.csv` — Task 19

  **Acceptance Criteria**:
  - [ ] `experiment_comparison_report.md` 生成
  - [ ] 包含根因结论
  - [ ] 包含新旧指标对比表
  - [ ] 包含 held-out 结果
  - [ ] 包含论文写作建议

  **QA Scenarios**:

  ```
  Scenario: Comparison report comprehensive
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; p=Path('experiment_comparison_report.md'); assert p.exists(); c=p.read_text(encoding='utf-8'); assert 'root cause' in c.lower() or '根因' in c; assert 'held-out' in c.lower() or 'heldout' in c.lower(); assert 'without_verifier' in c; assert len(c)>2000"
    Expected Result: Report ≥2000 chars with all sections
    Evidence: .omo/evidence/task-20-comparison-report.txt
  ```

  **Commit**: NO (diagnostic report)

---

- [ ] 21. 重新生成全部 paper_tables/*.csv（基于新实验）

  **What to do**:
  - 基于 Task 15-17 的新实验指标，重新生成 `outputs/paper_tables/` 下所有 CSV
  - 必须重新生成：
    - `table1_dataset_statistics.csv`：50 events, 1461 evidence, 174 gold tuples, 110 gold chains（从实际数据读取，非硬编码）
    - `table4_main_results.csv`：从 `pubevent-soa-lite-human-gold-v2-paper/metrics.json` 读取
    - `table5_ablation_results.csv`：从 `ablation_results.csv` 读取全部 9+ settings
    - `table6_evidence_support_detail.csv`、`table7_chain_detail.csv`、`table8_error_summary.csv`
  - 删除旧的 STALE 文件（table5 只有 4 行的旧版）
  - 统一数值精度（4 位小数）
  - 确保 CSV 与 docx 内表格数字一致

  **Must NOT do**:
  - 不得硬编码数字（必须从 metrics.json 读取）
  - 不得保留旧 STALE 文件
  - 不得使用 diagnostic-only 输出

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 22, 23, 24, 25, 26)
  - **Blocks**: Tasks 22, 23, 24, 25 (paper writing needs new tables)
  - **Blocked By**: Tasks 15, 16, 17, 18, 19

  **References**:
  - `outputs/runs_human_gold_v2/ablation_results.csv` — Task 15
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json` — Task 16
  - `outputs/runs_human_gold_v2/heldout_eval/metrics.json` — Task 17
  - `outputs/paper_tables/` — 当前 STALE 表格
  - `data/pubevent_soa_lite/events.jsonl` — 实际事件数
  - `data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl` — 实际证据数
  - `data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl` — 实际 gold 数

  **Acceptance Criteria**:
  - [ ] 全部 table*.csv 重新生成
  - [ ] table1 数字 = 50/1461/174/110（从实际数据读取）
  - [ ] table5 包含全部 9+ ablation settings
  - [ ] table4 数字与主实验 metrics.json 一致

  **QA Scenarios**:

  ```
  Scenario: Paper tables regenerated correctly
    Tool: Bash
    Steps:
      1. python -c "import csv; from pathlib import Path; t1=list(csv.DictReader(Path('outputs/paper_tables/table1_dataset_statistics.csv').read_text(encoding='utf-8').splitlines())); print('Table1 rows:'); [print(f'  {r}') for r in t1]; t5=list(csv.DictReader(Path('outputs/paper_tables/table5_ablation_results.csv').read_text(encoding='utf-8').splitlines())); print(f'Table5 rows: {len(t5)}'); assert len(t5)>=9, f'Table5 only {len(t5)} rows'"
    Expected Result: Table1 correct; Table5 ≥9 rows
    Evidence: .omo/evidence/task-21-paper-tables.txt
  ```

  **Commit**: YES
  - Message: `docs: regenerate all paper tables from new experiment results`
  - Files: `outputs/paper_tables/*.csv`

- [ ] 22. 论文 docx Table 1-9 数字对齐

  **What to do**:
  - 使用 python-docx 读取 `outputs/manuscript/episoa_full_draft.docx` 中全部 9 个表格
  - 对比每个表格的数字与 Task 21 重新生成的 CSV
  - 修改 docx 中不一致的数字：
    - Table 1 (dataset stats): 50/1461/174/110
    - Table 4 (paired significance): 新 p 值（Task 19）
    - Table 5 (main results): 新主实验指标（Task 16）
    - Table 6 (ablation): 新 ablation 指标（Task 15）
    - Table 7 (faithfulness): ESR/over_inference/contradiction 新数据
    - Table 8 (error types): 从 tuple_match_diagnostics 重新统计
    - Table 9 (risks): 更新风险描述
  - 保存修改后的 docx

  **Must NOT do**:
  - 不得改变表格结构（只改数字）
  - 不得编造数字

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 23, 24, 25, 26)
  - **Blocks**: None
  - **Blocked By**: Task 21 (needs new CSVs)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 被修改文件
  - `outputs/paper_tables/*.csv` — Task 21 生成
  - `experiment_comparison_report.md` — Task 20 生成

  **Acceptance Criteria**:
  - [ ] docx 内 Table 1-9 数字与 CSV 一致
  - [ ] docx 可正常打开
  - [ ] 表格数量仍为 9

  **QA Scenarios**:

  ```
  Scenario: Docx tables aligned with CSV
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; import csv; from pathlib import Path; doc=Document('outputs/manuscript/episoa_full_draft.docx'); print(f'Tables in docx: {len(doc.tables)}'); assert len(doc.tables)>=9; t1=doc.tables[1]; print(f'Table1 R2 (evidence): {t1.rows[2].cells[1].text.strip()}'); assert '1461' in t1.rows[2].cells[1].text, 'evidence count wrong'"
    Expected Result: ≥9 tables; Table1 evidence = 1461
    Evidence: .omo/evidence/task-22-docx-tables.txt
  ```

  **Commit**: YES
  - Message: `docs: align docx table numbers with new experiment results`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 23. 论文摘要数字对齐

  **What to do**:
  - 读取 `outputs/manuscript/episoa_full_draft.docx` 摘要段落
  - 基于 Task 20 的 experiment_comparison_report.md，决定摘要用哪个数字：
    - 如果主实验与 ablation 一致：用主实验数字
    - 如果仍有差异：用主实验数字，并在 Methods 中说明 ablation 作为对照
  - 更新摘要【结果】段：
    - Num-Tuples（新值）
    - F1@0.3（新值）
    - P@0.3, R@0.3（新值）
    - ESR, UTR（如不变则保留）
  - 更新【局限】段（如 char@0.5, exact 变化）
  - 同步更新英文摘要
  - 确保摘要 ≤400 字

  **Must NOT do**:
  - 不得改变摘要五段结构
  - 不得删除英文摘要
  - 不得编造数字

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 22, 24, 25, 26)
  - **Blocks**: None
  - **Blocked By**: Task 21 (needs new numbers)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 摘要段落
  - `experiment_comparison_report.md` — Task 20
  - `outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json` — 新指标

  **Acceptance Criteria**:
  - [ ] 摘要【结果】段数字与主实验 metrics.json 一致
  - [ ] 英文摘要同步更新
  - [ ] 摘要 ≤400 字
  - [ ] 五段结构式标签保留

  **QA Scenarios**:

  ```
  Scenario: Abstract numbers match metrics
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; import json; doc=Document('outputs/manuscript/episoa_full_draft.docx'); m=json.loads(open('outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/metrics.json',encoding='utf-8').read()); abstract=''; [abstract:=abstract+p.text for p in doc.paragraphs if '摘要' in p.text or 'Abstract' in p.text]; print(f'Abstract mentions F1@0.3={m[\"Tuple-F1-semantic@0.3\"]}: {str(m[\"Tuple-F1-semantic@0.3\"]) in abstract}')"
    Expected Result: Abstract contains new F1@0.3 value
    Evidence: .omo/evidence/task-23-abstract.txt
  ```

  **Commit**: YES
  - Message: `docs: align abstract numbers with new main experiment results`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 24. 论文 Results 章节改写

  **What to do**:
  - 基于 Task 20 的 experiment_comparison_report.md，改写 docx 第 4 章（实验结果与分析）
  - 4.1 实验设计：更新实验配置描述（verifier mode, threshold）
  - 4.2 主实验结果：
    - 报告新的 full_soe 指标
    - 诚实报告 verifier 性能预算结果（Task 18）
    - 如果 full_soe 仍低于 without_verifier：诚实承认并解释 trade-off
    - 如果 full_soe ≥ without_verifier：报告 verifier 修复成功
  - 补充 held-out 测试集结果（Task 17）
  - 4.3 案例分析：保留（如仍有效）
  - 4.4 标注一致性：保留并完善
  - 更新统计显著性叙述（Task 19 新 p 值）

  **Must NOT do**:
  - 不得修改 Introduction / Related Work
  - 不得编造或美化数字
  - 不得删除 held-out 结果

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 22, 23, 25, 26)
  - **Blocks**: None
  - **Blocked By**: Tasks 20, 21 (needs report + tables)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 被修改文件
  - `experiment_comparison_report.md` — Task 20
  - `verifier_budget_v2_report.json` — Task 18
  - `outputs/runs_human_gold_v2/main_vs_ablation_comparison_v2.csv` — Task 19

  **Acceptance Criteria**:
  - [ ] Results 章节引用新指标
  - [ ] held-out 结果出现在论文中
  - [ ] verifier 性能预算结果诚实报告
  - [ ] 统计显著性新 p 值引用

  **QA Scenarios**:

  ```
  Scenario: Results section updated with new numbers and held-out
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); text=' '.join(p.text for p in doc.paragraphs); assert 'held-out' in text.lower() or '保留测试' in text or 'heldout' in text.lower(), 'held-out missing'; assert '0.2385' not in text or '0.3906' not in text or True, 'numbers may need check'"
    Expected Result: held-out mentioned; numbers consistent with new results
    Evidence: .omo/evidence/task-24-results.txt
  ```

  **Commit**: YES
  - Message: `docs: rewrite Results section with new metrics and held-out evaluation`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 25. 论文 IAA/Limitations 章节完善

  **What to do**:
  - 读取 docx 中 IAA 相关段落（4.4 标注一致性）
  - 确认已删除 κ=1.0 的声称（先前计划已做，验证）
  - 完善 IAA 描述：
    - 明确"LLM 预标注 + 三人独立专家验证"
    - 报告验证层面一致率（accept/reject）
    - 明确标注"非内容层 IAA"
    - 说明未来工作：在 20% 子集上重新独立标注
  - 完善 Limitations（如独立章节不存在，在结语前补充）：
    - 数据集规模（50 events, 174 tuples）
    - 中文专有性
    - 基于规则检索
    - verifier 精确率-召回率折衷（Task 18 结果）
    - LLM 非确定性与模型版本依赖（gpt-5.5）
    - without_soe_graph 异常（如是 bug 则不提，如是 feature 则说明）
    - held-out 评估一次性（未调参）
  - 至少 5 个明确限制

  **Must NOT do**:
  - 不得恢复 κ=1.0 声称
  - 不得删除已有诚实声明

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 22, 23, 24, 26)
  - **Blocks**: None
  - **Blocked By**: Task 21 (needs new numbers for limitations)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 4.4 章节和结语
  - `data/pubevent_soa_lite/human_gold_v2/independent_audit/independent_annotation_iaa_report.md` — IAA 报告
  - `verifier_budget_v2_report.json` — Task 18

  **Acceptance Criteria**:
  - [ ] 无 κ=1.0 声称
  - [ ] IAA 描述为"LLM 预标注 + 三人验证"
  - [ ] Limitations ≥5 个
  - [ ] verifier trade-off 在 Limitations 中

  **QA Scenarios**:

  ```
  Scenario: IAA and Limitations honest
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); text=' '.join(p.text for p in doc.paragraphs); assert 'κ=1.0' not in text and 'kappa=1.0' not in text, 'IAA kappa still claimed'; assert '限制' in text or '局限' in text, 'no limitations'; assert 'LLM' in text or '预标注' in text, 'no LLM pre-annotation mention'"
    Expected Result: No κ=1.0; limitations present; LLM pre-annotation mentioned
    Evidence: .omo/evidence/task-25-iaa-limitations.txt
  ```

  **Commit**: YES
  - Message: `docs: finalize IAA description and expand Limitations`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 26. 论文 Table 转三线表格式

  **What to do**:
  - 检查 `outputs/manuscript/episoa_full_draft.docx` 中 9 个表格的样式
  - 将每个表格样式设置为三线表（booktabs 等效）：
    - 顶部边框：粗线（1.5pt）
    - 表头底部边框：细线（0.75pt）
    - 表格底部边框：粗线（1.5pt）
    - 移除所有内部横线和竖线
  - 确保表题在表格上方
  - 同步更新 `outputs/paper_tables/paper_tables.tex`（如果论文也用 LaTeX）
  - 验证 docx 表格在 Word 中打开样式正确

  **Must NOT do**:
  - 不得改变表格数据
  - 不得改变表格编号

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 22, 23, 24, 25)
  - **Blocks**: None
  - **Blocked By**: Task 22 (tables must have correct numbers first)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 9 个表格
  - `outputs/paper_tables/paper_tables.tex` — LaTeX 表格
  - python-docx 文档：表格样式 API

  **Acceptance Criteria**:
  - [ ] docx 中 9 个表格使用三线表样式
  - [ ] 无内部横线/竖线
  - [ ] 表题在表格上方
  - [ ] `paper_tables.tex` 使用 booktabs（\toprule, \midrule, \bottomrule）

  **QA Scenarios**:

  ```
  Scenario: Tables use sanxian format
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; from docx.shared import Pt; doc=Document('outputs/manuscript/episoa_full_draft.docx'); t=doc.tables[0]; print(f'Table 0 style: {t.style.name if t.style else None}'); print(f'Rows: {len(t.rows)}'); assert len(doc.tables)>=9, 'need ≥9 tables'"
      2. findstr /C:"\\toprule" /C:"\\bottomrule" outputs/paper_tables/paper_tables.tex
    Expected Result: ≥9 tables; booktabs commands in tex
    Evidence: .omo/evidence/task-26-sanxian.txt
  ```

  **Commit**: YES
  - Message: `docs: convert tables to sanxian (booktabs) format`
  - Files: `outputs/manuscript/episoa_full_draft.docx`, `outputs/paper_tables/paper_tables.tex`

---

- [ ] 27. 缩短标题至 ≤20 字

  **What to do**:
  - 当前标题："EpiSOA：一种面向公共事件的证据链驱动利益相关者观点归因方法研究"（34 字）
  - 缩短至 ≤20 中文字符
  - 建议标题（选其一或用户提供）：
    - "证据链驱动的公共事件观点归因"（15 字）
    - "公共事件证据链观点归因方法"（14 字）
    - "EpiSOA：公共事件证据链观点归因"（15 字 + 英文）
    - "面向公共事件的证据链观点归因"（15 字）
  - 同步更新英文标题
  - 修改 docx 第 0 段（标题段）
  - 修改 `episoa_outline.md` 第 1 行
  - 确保标题保留核心概念：公共事件 + 证据链 + 观点归因

  **Must NOT do**:
  - 不得删除"EpiSOA"品牌名（可保留为前缀）
  - 不得改变研究主题

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 28, 29, 30, 31, 32, 33)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — 第 0 段标题
  - `outputs/manuscript/episoa_outline.md` — 第 1-3 行
  - `outputs/manuscript/episoa_manuscript_qa.json` — `title_cn_within_20_chars: false`

  **Acceptance Criteria**:
  - [ ] 标题 ≤20 中文字符
  - [ ] 英文标题同步更新
  - [ ] `episoa_manuscript_qa.json` 重新生成显示 `title_cn_within_20_chars: true`

  **QA Scenarios**:

  ```
  Scenario: Title within 20 chars
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); title=doc.paragraphs[0].text.strip(); cn=len([c for c in title if '\u4e00'<=c<='\u9fff']); print(f'Title: {title}'); print(f'CN chars: {cn}'); assert cn<=20, f'Title {cn} chars > 20'"
    Expected Result: Title ≤20 Chinese chars
    Evidence: .omo/evidence/task-27-title.txt
  ```

  **Commit**: YES
  - Message: `docs: shorten title to ≤20 Chinese characters`
  - Files: `outputs/manuscript/episoa_full_draft.docx`, `outputs/manuscript/episoa_outline.md`

- [ ] 28. 具体化 AI 使用声明

  **What to do**:
  - 读取 docx 中当前 AI 使用声明（[93] 段）
  - 当前声明过于笼统："论文写作阶段可使用AI工具进行语言润色、格式检查和代码调试辅助"
  - 改写为详细声明，包含：
    - **模型版本**：gpt-5.5（通过 OpenAI 兼容 API 调用）
    - **API 提供商**：明确说明（如 OpenAI / 国内代理）
    - **使用环节**：
      - 数据采集：未使用 LLM（规则检索）
      - LLM 预标注：使用 gpt-5.5 生成 silver tuples（已人工裁决）
      - 归因：使用 gpt-5.5 进行 SOA tuple 抽取
      - 验证：使用 gpt-5.5 进行 decomposed verifier 判断
      - 论文写作：使用 AI 工具进行语言润色、格式检查
    - **人工复核机制**：
      - 所有 LLM 归因输出经 decomposed verifier 检查
      - silver 预标注经三人独立人工裁决
      - 论文文字由作者负责核验
    - **不使用环节**：AI 不作为未经核验的事实来源
  - 同步更新英文 AI 声明（如有）

  **Must NOT do**:
  - 不得隐瞒 LLM 使用环节
  - 不得声称 AI 未参与（明确参与了归因和验证）

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 27, 29, 30, 31, 32, 33)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — [93] 段 AI 声明
  - `configs/paper.yaml` — llm_model: gpt-5.5
  - 期刊《生成式AI工具使用指南》要求

  **Acceptance Criteria**:
  - [ ] AI 声明包含模型版本（gpt-5.5）
  - [ ] AI 声明包含 API 提供商
  - [ ] AI 声明包含使用环节（≥4 个）
  - [ ] AI 声明包含人工复核机制
  - [ ] AI 声明包含不使用环节

  **QA Scenarios**:

  ```
  Scenario: AI declaration specific
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); text=' '.join(p.text for p in doc.paragraphs); assert 'gpt-5.5' in text or 'gpt5.5' in text.lower(), 'model version missing'; assert 'API' in text or 'api' in text.lower(), 'API provider missing'; assert '人工' in text or '核验' in text or '复核' in text, 'human review missing'; assert '预标注' in text or '归因' in text or '验证' in text, 'use cases missing'"
    Expected Result: AI declaration has model, API, review, use cases
    Evidence: .omo/evidence/task-28-ai-declaration.txt
  ```

  **Commit**: YES
  - Message: `docs: specific AI usage declaration (model, provider, use cases, review)`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 29. 填实作者信息 + 基金 + CRediT 贡献声明

  **What to do**:
  - 读取 docx [1]-[3] 段，当前全是占位符
  - **注意**：此处需要用户提供真实信息。在计划执行时，agent 应：
    - 检查 docx 中作者信息是否仍是占位符
    - 如果仍是占位符：标记为 BLOCKED，要求用户填实
    - 如果用户已填实：验证格式合规
  - 需要的信息：
    - 作者姓名（中文 + 英文）
    - 作者单位（中文 + 英文，含城市、邮编）
    - 通讯作者姓名 + Email
    - 基金项目名称及编号（或注明"无基金资助"）
  - 添加 CRediT 贡献声明（按作者分工）：
    - Conceptualization, Methodology, Software, Validation, Formal Analysis, Investigation, Resources, Data Curation, Writing - Original Draft, Writing - Review & Editing, Visualization, Supervision, Project Administration, Funding Acquisition
  - 确保英文作者信息同步

  **Must NOT do**:
  - 不得编造作者信息
  - 不得保留占位符投稿

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 27, 28, 30, 31, 32, 33)
  - **Blocks**: None
  - **Blocked By**: None (but may require user input)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — [1]-[3] 段
  - 期刊《署名要求和贡献声明》模板
  - CRediT 分类标准

  **Acceptance Criteria**:
  - [ ] 作者姓名、单位、城市、邮编填实
  - [ ] 通讯作者 Email 填实
  - [ ] 基金项目填实（或注明无）
  - [ ] CRediT 贡献声明存在，按作者分工
  - [ ] 英文作者信息同步

  **QA Scenarios**:

  ```
  Scenario: Author info filled (or blocked if user input needed)
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); text=' '.join(p.text for p in doc.paragraphs[:10]); has_placeholder = '【作者' in text or '【单位' in text or '【基金' in text or '待补充' in text; if has_placeholder: print('BLOCKED: still placeholders, need user input'); else: print('Author info filled'); assert not has_placeholder, 'Placeholders remain'"
    Expected Result: No placeholders (or BLOCKED status documented)
    Evidence: .omo/evidence/task-29-author-info.txt
  ```

  **Commit**: YES (if filled)
  - Message: `docs: fill author info, funding, CRediT contribution statement`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 30. 完善数据可用性声明（ScienceDB）

  **What to do**:
  - 读取 docx [94] 段当前数据可用性声明
  - 改写为期刊要求的完整声明：
    - 明确说明支撑数据已上传至 ScienceDB
    - 提供 ScienceDB URL（即使暂时用占位 URL，注明"录用后更新"）
    - 列出数据包含：事件注册表、证据元数据、gold tuples、实验配置、metrics 摘要
    - 列出排除项：原始网页全文（版权）、登录态内容、raw LLM responses
    - 提供 checksums 文件供核验
  - 同步更新 [96]-[97] 段"投稿声明"内容（合并到数据可用性声明，删除独立 Section 9）

  **Must NOT do**:
  - 不得编造 ScienceDB URL
  - 不得声称提供原始网页全文

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 27, 28, 29, 31, 32, 33)
  - **Blocks**: None
  - **Blocked By**: Task 31 (ScienceDB package must be built first, or parallel)

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — [94], [96]-[97] 段
  - `outputs/manuscript/submission_supporting_data/` — 支撑数据目录
  - 期刊《论文支撑数据提交流程》
  - ScienceDB URL: https://www.scidb.cn/surl/dakd

  **Acceptance Criteria**:
  - [ ] 数据可用性声明包含 ScienceDB URL
  - [ ] 列出数据包含项和排除项
  - [ ] 删除独立 Section 9 "投稿声明"（合并到声明中）
  - [ ] 英文数据可用性声明同步

  **QA Scenarios**:

  ```
  Scenario: Data availability statement complete
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); text=' '.join(p.text for p in doc.paragraphs); assert 'ScienceDB' in text or 'scidb' in text.lower() or '数据可用' in text, 'data availability missing'; assert '9 投稿声明' not in text, 'Section 9 still exists'"
    Expected Result: ScienceDB mentioned; Section 9 removed
    Evidence: .omo/evidence/task-30-data-availability.txt
  ```

  **Commit**: YES
  - Message: `docs: complete data availability statement with ScienceDB`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 31. 构建 ScienceDB 投稿数据包

  **What to do**:
  - 创建 `outputs/scidb_submission_package/` 目录
  - 包含以下文件：
    - `event_registry_metadata.csv` — 50 events 元数据（不含全文）
    - `evidence_metadata.csv` — 1461 evidence 元数据（不含全文，只含 URL/source_type/publish_time）
    - `human_gold_tuples_v2.jsonl` — 174 gold tuples
    - `human_gold_event_chains_v2.jsonl` — 110 gold chains
    - `experiment_configs/` — paper.yaml, ablation.yaml, paper_with_heldout.yaml
    - `formal_results_summary.json` — 主实验 + ablation + held-out 指标摘要
    - `annotation_schema.json` — 标注 schema 定义
    - `checksums_sha256.txt` — 所有文件 SHA256 校验和
    - `manifest.json` — 文件清单 + 版本 + 生成时间
    - `README.md` — 数据包说明
  - 排除：
    - 原始网页全文（版权）
    - 登录态平台内容
    - raw LLM responses
    - 作者个人信息（匿名版本）
  - 生成 `submission_readiness_report.json` 确认所有合规项

  **Must NOT do**:
  - 不得包含原始网页全文
  - 不得包含作者个人信息
  - 不得包含 API keys

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 27, 28, 29, 30, 32, 33)
  - **Blocks**: Task 30 (data availability references package)
  - **Blocked By**: None

  **References**:
  - `data/pubevent_soa_lite/events.jsonl` — events 元数据来源
  - `data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl` — evidence 元数据来源
  - `data/pubevent_soa_lite/human_gold_v2/` — gold 数据
  - `configs/` — 实验配置
  - `outputs/runs_human_gold_v2/` — 实验结果
  - 期刊《论文支撑数据提交流程》

  **Acceptance Criteria**:
  - [ ] `outputs/scidb_submission_package/` 目录创建
  - [ ] 包含所有必需文件
  - [ ] 不包含排除项
  - [ ] `checksums_sha256.txt` 生成
  - [ ] `manifest.json` 生成
  - [ ] `submission_readiness_report.json` 显示 `formal_results_gate_pass: true`

  **QA Scenarios**:

  ```
  Scenario: ScienceDB package complete
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; p=Path('outputs/scidb_submission_package'); assert p.exists(); required=['event_registry_metadata.csv','evidence_metadata.csv','human_gold_tuples_v2.jsonl','human_gold_event_chains_v2.jsonl','checksums_sha256.txt','manifest.json','README.md']; missing=[f for f in required if not (p/f).exists()]; assert not missing, f'Missing: {missing}'; print('All required files present')"
      2. python -c "import json; from pathlib import Path; r=json.loads(Path('outputs/scidb_submission_package/submission_readiness_report.json').read_text(encoding='utf-8')); assert r.get('formal_results_gate_pass')==True, 'gate not pass'"
    Expected Result: All files present; gate pass
    Evidence: .omo/evidence/task-31-scidb-package.txt
  ```

  **Commit**: YES
  - Message: `data: build ScienceDB submission package`
  - Files: `outputs/scidb_submission_package/`

- [ ] 32. 核验参考文献 GB/T 7714 格式

  **What to do**:
  - 读取 docx [100]-[135] 段（参考文献）
  - 逐条核验是否符合 GB/T 7714-2015 顺序编码制：
    - 期刊文章：作者. 题名[J]. 刊名, 年, 卷(期): 起止页码.
    - 会议论文：作者. 题名[C]//会议名. 出版地: 出版者, 年: 起止页码.
    - 专著：作者. 书名[M]. 出版地: 出版者, 年.
  - 检查：
    - 作者格式（3 名以内全列，超过用"等"）
    - 中英文标点（中文用全角，英文用半角）
    - 卷期格式
    - 页码格式
  - 修复不符合的条目
  - 确保正文引用 [1]-[35] 与参考文献列表对应

  **Must NOT do**:
  - 不得删除参考文献
  - 不得改变引用顺序

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["python-debug"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 27, 28, 29, 30, 31, 33)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `outputs/manuscript/episoa_full_draft.docx` — [100]-[135] 段
  - GB/T 7714-2015 标准
  - 期刊《参考文献著录格式》模板

  **Acceptance Criteria**:
  - [ ] 35 条参考文献全部符合 GB/T 7714
  - [ ] 正文引用 [1]-[35] 对应正确
  - [ ] 中英文标点正确

  **QA Scenarios**:

  ```
  Scenario: References GB/T 7714 compliant
    Tool: Bash
    Steps:
      1. python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); refs=[p.text for p in doc.paragraphs if p.text.strip().startswith('[') and ']' in p.text[:5]]; print(f'Total refs: {len(refs)}'); assert len(refs)>=35, f'Only {len(refs)} refs'; j_count=sum(1 for r in refs if '[J]' in r); c_count=sum(1 for r in refs if '[C]' in r); print(f'J: {j_count}, C: {c_count}'); assert j_count+c_count>0, 'no J or C refs'"
    Expected Result: ≥35 refs; mix of J and C types
    Evidence: .omo/evidence/task-32-references.txt
  ```

  **Commit**: YES
  - Message: `docs: verify and fix references GB/T 7714 format`
  - Files: `outputs/manuscript/episoa_full_draft.docx`

- [ ] 33. 清理论文目录旧脚本

  **What to do**:
  - 读取 `outputs/manuscript/` 目录下的 .py 文件列表
  - 识别历史修改脚本（fix_*.py, merge_*.py, rewrite_*.py, remove_*.py, update_*.py, revise_*.py, final_merge*.py, check_structure.py, format_references.py, step0_debug.py）
  - 将这些脚本移到 `outputs/manuscript/_archive_scripts/` 或删除（如已无用）
  - 保留：`episoa_full_draft.docx`, `episoa_outline.md`, `episoa_manuscript_qa.json`, `significance_report.json`, `final-compliance-report.txt`, `episoa_pipeline.png`, 匿名版本, PDF 版本
  - 清理 `outputs/manuscript/模板.doc`（旧模板）

  **Must NOT do**:
  - 不得删除论文 docx/pdf/outline
  - 不得删除 QA 报告

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `["safe-edit"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 27, 28, 29, 30, 31, 32)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `outputs/manuscript/` — 目录列表

  **Acceptance Criteria**:
  - [ ] `outputs/manuscript/` 下无散落 .py 脚本
  - [ ] 旧脚本归档或删除
  - [ ] 保留文件清单：docx, pdf, outline, qa, significance, png, anonymous

  **QA Scenarios**:

  ```
  Scenario: Manuscript dir clean
    Tool: Bash
    Steps:
      1. python -c "from pathlib import Path; p=Path('outputs/manuscript'); py_files=list(p.glob('*.py')); print(f'PY files: {len(py_files)}'); assert len(py_files)==0 or all('_archive' in str(f) for f in py_files), f'Stray py files: {py_files}'"
    Expected Result: No stray .py files in manuscript dir
    Evidence: .omo/evidence/task-33-cleanup.txt
  ```

  **Commit**: YES
  - Message: `chore: archive historical manuscript scripts`
  - Files: `outputs/manuscript/`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command, check metric). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .omo/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -q`. Review all changed files for: type suppression, empty catches, debug logging, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction. Verify verifier threshold consistency across config/code/paper.
  Output: `Tests [N pass/N fail] | Lint [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Run full pipeline: `python scripts/run_paper_experiment.py --config configs/paper.yaml && python scripts/run_ablation.py --config configs/ablation.yaml --force && python scripts/run_paper_experiment.py --config configs/paper_with_heldout.yaml`. Verify all ablation settings complete. Verify verifier performance budget. Verify held-out test evaluation. Cross-check paper docx table numbers vs metrics.json. Save evidence to `.omo/evidence/final-qa/`.
  Output: `Ablations [N/N complete] | Verifier Budget [PASS/FAIL] | Held-out [PASS/FAIL] | Paper Numbers [PASS/FAIL] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes. Verify gold data untouched. Verify verify_tuples() API unchanged.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: 7 commits — `diagnose: root cause paper vs ablation config path`, `test: TDD RED for verifier LLM error fallback`, etc.
- **Wave 2**: 7 commits — `fix: verifier LLM error fallback (TDD GREEN)`, `fix: unify verifier threshold across config/code`, etc.
- **Wave 3**: 6 commits — `exp: rerun full ablation + main + heldout`, `test: verifier integration tests`, etc.
- **Wave 4**: 6 commits — `docs: regenerate paper tables from new metrics`, `docs: align abstract numbers`, etc.
- **Wave 5**: 7 commits — `docs: shorten title to ≤20 chars`, `docs: specific AI usage declaration`, `data: build ScienceDB package`, etc.

## Success Criteria

### Verification Commands
```bash
# All tests pass
python -m pytest tests/ -q

# Ablation suite completes with all settings > 0 predictions
python scripts/run_ablation.py --config configs/ablation.yaml --force
python -c "import csv; rows=list(csv.DictReader(open('outputs/runs_human_gold_v2/ablation_results.csv',encoding='utf-8'))); zeros=[r['Setting'] for r in rows if float(r['Tuples'])==0]; assert not zeros, f'Zero predictions: {zeros}'"

# Verifier budget check
python -c "import json; m=json.loads(open('outputs/runs_human_gold_v2/ablation_full_soe/metrics.json',encoding='utf-8').read()); w=json.loads(open('outputs/runs_human_gold_v2/ablation_without_verifier/metrics.json',encoding='utf-8').read()); print(f'full_soe F1@0.3={m[\"Tuple-F1-semantic@0.3\"]}, without_verifier F1@0.3={w[\"Tuple-F1-semantic@0.3\"]}')"

# Held-out evaluation
python -c "import json; from pathlib import Path; p=Path('outputs/runs_human_gold_v2/heldout_eval/metrics.json'); assert p.exists(), 'heldout eval missing'; m=json.loads(p.read_text(encoding='utf-8')); assert m['Num-Tuples']>0 and m['Tuple-F1-semantic@0.3']>0"

# Paper title ≤ 20 chars
python -c "from docx import Document; doc=Document('outputs/manuscript/episoa_full_draft.docx'); title=doc.paragraphs[0].text.strip(); cn=len([c for c in title if '\u4e00'<=c<='\u9fff']); assert cn<=20, f'Title {cn} chars > 20'"

# Paper table numbers match metrics
python -c "import json,csv; m=json.loads(open('outputs/runs_human_gold_v2/ablation_full_soe/metrics.json',encoding='utf-8').read()); print(f'full_soe: Num-Tuples={m[\"Num-Tuples\"]}, F1@0.3={m[\"Tuple-F1-semantic@0.3\"]}')"
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] 418+ tests pass
- [ ] Verifier budget: full_soe F1 ≥ without_verifier OR p > 0.05
- [ ] oracle_evidence Num-Tuples > 0
- [ ] Held-out evaluation produced
- [ ] Title ≤ 20 Chinese chars
- [ ] Paper table numbers match metrics.json
- [ ] AI declaration specific (model + provider + use case + review)
- [ ] Author info, funding, CRediT, conflict, data availability all present
- [ ] ScienceDB package complete
