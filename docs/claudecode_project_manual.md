# EpiSOA 论文项目 Claude Code 说明书

> 建议文件位置：`docs/claudecode_project_manual.md`  
> 适用对象：Claude Code / DeepSeek API 接入环境  
> 目的：让 Claude Code 在接手 EpiSOA 时准确理解论文流程、数据流、输入输出文件、当前完成状态和后续任务，避免误跑旧 pipeline、误删中间成果或使用错误 evidence namespace。

---

## 0. 项目一句话定义

EpiSOA 是一个面向公共事件的 **Evidence-grounded Stakeholder Opinion Attribution** 论文项目，核心任务是从多源公开证据中抽取并验证：

```text
<Event, Stakeholder, Opinion, Sentiment, Rationale, EventChain, EvidenceIDs>
```

中文可理解为：

```text
<事件, 利益相关方, 观点/诉求, 情感倾向, 归因理由, 事件链, 支撑证据ID>
```

项目不是普通舆情情感分类，而是 **证据约束下的“利益相关方—观点—情绪—原因—事件链”结构化归因任务**。论文贡献应围绕数据集构建、证据约束任务定义、事件链支撑、LLM/RAG/verification pipeline 和 benchmark evaluation 展开。

---

## 1. Claude Code 操作总原则

### 1.1 当前项目状态优先级

Claude Code 接手时，必须优先使用当前已经跑通的 repaired/gold/benchmark 文件，不要退回 README 中的旧默认文件名。

当前 canonical 版本为：

```text
v3_repaired_plus_low37_gold
```

核心 canonical evidence 文件是：

```text
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

Gold annotation canonical 目录是：

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/
```

Benchmark canonical 输出目录是：

```text
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/
```

### 1.2 禁止事项

除非用户明确要求，否则 Claude Code 不得执行：

```bash
python scripts/reset_workspace.py
```

原因：该脚本会回到空数据骨架，可能删除/清空已经完成的数据构建成果。

不得使用下面文件做 gold audit：

```text
data/pubevent_soa_lite/evidence_filtered.jsonl
```

原因：当前 gold tuples 和 gold chains 引用的是 repaired evidence namespace，即：

```text
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

不得在没有 dry-run、audit 和自动备份的情况下覆盖：

```text
llm_gold_tuples.jsonl
llm_gold_event_chains.jsonl
evidence_v3_repaired_plus_low37.jsonl
```

不得把 `public_social` 理解为登录态社交平台爬虫。项目采集范围只包括公开网页、搜索可索引页面、新闻/论坛/聚合页中引用的公开社交内容。

---

## 2. 论文整体流程

EpiSOA 的论文流程可以分为 8 个环节：

```text
A. Formal Event Registry
   ↓
B. C-FSM Evidence Collection
   ↓
C. Evidence Cleaning / Normalization / Source Typing
   ↓
D. Annotation Input Construction
   ↓
E. LLM Pre-annotation + Human Verification
   ↓
F. Gold Tuple / Gold Event Chain Release
   ↓
G. Benchmark Task Construction
   ↓
H. Model Experiment / Ablation / Evaluation / Paper Tables
```

README 中的正式流程是 5 步：

```text
1. Formal event registry construction
2. Evidence collection with C-FSM
3. Evidence normalization and annotation sheet generation
4. LLM preannotation, human review, and gold export
5. Experiment execution and evaluation
```

当前项目实际已经扩展到 benchmark construction 阶段，因此建议 Claude Code 按 8 环节版本理解。

---

## 3. 各环节输入、脚本、输出、状态

### A. Formal Event Registry

#### 目标

建立正式公共事件注册表。每个事件必须是具体公共事件，而不是抽象 topic。事件应包含事实地点、时间窗口、触发因素、锚定实体、anchor URL、source scope 和 query seeds。

#### 输入

人工筛选后的事件定义。

#### 核心文件

```text
data/pubevent_soa_lite/events.jsonl
```

#### 校验命令

```bash
python scripts/validate_events.py
```

#### 输出

通过校验的事件注册表。

#### 当前状态

已完成。当前 benchmark 使用：

```text
50 events
```

---

### B. C-FSM Evidence Collection

#### 目标

围绕每个事件跨来源采集公开证据，覆盖官方、新闻、论坛、公开社交引用、公共网页等来源，并通过 C-FSM repair loop 修复 coverage 缺口。

#### 输入

```text
data/pubevent_soa_lite/events.jsonl
configs/collector.yaml
configs/source_detection.yaml
```

#### 主要脚本

```text
scripts/collect_evidence.py
```

#### 常规命令

```bash
python scripts/collect_evidence.py
```

断点续跑：

```bash
python scripts/collect_evidence.py --resume
```

定向补采/recollection 模式：

```bash
python scripts/collect_evidence.py \
  --events data/pubevent_soa_lite/events_missing_or_low_coverage.jsonl \
  --config configs/collector_budget_50.yaml \
  --output outputs/runs/collector_repair_xxx/raw.jsonl \
  --query-plan-output outputs/runs/collector_repair_xxx/query_plan.jsonl \
  --coverage-output outputs/runs/collector_repair_xxx/coverage.json \
  --planner-debug-output outputs/runs/collector_repair_xxx/planner_debug.json \
  --debug-output outputs/runs/collector_repair_xxx/recollection_debug.json \
  --max-events N
```

#### 输出

典型输出包括：

```text
outputs/runs/{collector_run_id}/raw.jsonl
outputs/runs/{collector_run_id}/query_plan.jsonl
outputs/runs/{collector_run_id}/coverage.json
outputs/runs/{collector_run_id}/planner_debug.json
outputs/runs/{collector_run_id}/recollection_debug.json
data/pubevent_soa_lite/interim/query_planner_debug.json
data/pubevent_soa_lite/interim/coverage.json
```

注意：

```text
coverage.json 是 JSON，不是 JSONL。
读取时使用 json.load，不要逐行 json.loads。
```

#### 当前状态

已完成全量采集与 low37 修复。当前 benchmark 使用 clean/repaired evidence：

```text
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

统计结果：

```text
Events:   50
Evidence: 1767
```

---

### C. Evidence Cleaning / Normalization / Source Typing

#### 目标

将 raw evidence 清洗成正式 evidence namespace，完成去重、source_type 统一、字段规范化和 annotation-ready 证据池构建。

#### 输入

```text
outputs/runs/{collector_run_id}/raw.jsonl
configs/source_detection.yaml
```

#### 主要脚本

```text
scripts/normalize_evidence.py
scripts/normalize_evidence_source_type.py
```

#### Gold 阶段 source_type 规范化命令

Dry-run：

```bash
python scripts/normalize_evidence_source_type.py \
  --input data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --dry-run
```

正式执行：

```bash
python scripts/normalize_evidence_source_type.py \
  --input data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

#### 输出

```text
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

#### 质量门槛

论文正式版数据构建建议采用以下标准：

```text
raw 采集层：每个事件 50–60 条 evidence
clean evidence 层：每个事件 30–35 条 evidence
LLM 标注输入层：每个事件 20–25 条 evidence
最终 gold 支撑证据：每个事件 10–15 条 evidence
```

同时要检查：

```text
source balance
unique URL 去重
official coverage
interaction-class coverage
source_type completeness
missing evidence references
```

#### 当前状态

已完成。当前 clean/repaired evidence 数量为：

```text
1767 evidence / 50 events ≈ 35.34 evidence per event
```

与 clean evidence 层 30–35 条/事件的一区论文构建标准基本一致。

---

### D. Annotation Input Construction

#### 目标

从 clean evidence 中构造给 LLM 或人工标注使用的输入表。

#### 输入

```text
data/pubevent_soa_lite/events.jsonl
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

#### 主要脚本

```text
scripts/make_annotation_sheet.py
scripts/run_llm_gold_preannotation.py
scripts/build_gold_review_sheets.py
```

#### 输出

常见输出包括：

```text
data/pubevent_soa_lite/annotation/
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/
```

其中当前正式 gold annotation 目录是：

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/
```

#### 当前状态

已完成。后续 Claude Code 不应重新大规模生成 annotation sheet，除非需要补充新事件或修复特定 gold 缺口。

---

### E. LLM Pre-annotation + Human Verification

#### 目标

利用 LLM 预标注 SOA tuple 和 event chain，再通过人工审阅/抽查修复错误，形成 gold dataset。

#### 输入

```text
data/pubevent_soa_lite/events.jsonl
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/
```

#### 主要脚本

```text
scripts/run_llm_gold_preannotation.py
scripts/build_gold_review_sheets.py
scripts/convert_review_sheets_to_gold.py
scripts/normalize_chain_ids.py
scripts/audit_gold_annotation.py
scripts/build_annotation_expansion_plan.py
scripts/audit_annotation_expansion_delta.py
scripts/merge_annotation_expansion.py
scripts/write_gold_manifest.py
```

#### Gold canonical 文件

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl
```

#### Chain ID 规范化

Dry-run：

```bash
python scripts/normalize_chain_ids.py \
  --input data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --dry-run
```

正式执行：

```bash
python scripts/normalize_chain_ids.py \
  --input data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl
```

chain_id 规范：

```text
CHAIN_{event_id}_{序号}
例：CHAIN_E001_001
```

#### Gold audit 命令

```bash
python scripts/audit_gold_annotation.py \
  --events data/pubevent_soa_lite/events.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --output data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/final_audit.json
```

#### 当前状态

已完成 gold 修复与审计。

已确认的最终状态：

```text
Gold tuples: 188
Gold chains: 138
Total audit issues: 0
Ready for final gold: true
```

已完成 targeted tuple-chain coverage repair：

```text
E004
E010
E049
```

已修复链条：

```text
CHAIN_E004_003      += ev-00076
CHAIN_E010_001      += ev-00238
CHAIN_E010_EXP_001  += ev-00225
CHAIN_E049_001      += ev-01400, ev-01390
CHAIN_E049_EXP_001  event_chain text Unicode escape repair
```

Spot-check 状态：

```text
E004/E010/E028/E030/E040/E049
21 target tuples
21 linked to chains
31 review rows
0 missing evidence refs
31 rows have non-empty chain_ids
```

---

### F. Gold Tuple / Gold Event Chain Release

#### 目标

形成可复现实验和 benchmark 构建使用的 gold release。

#### 输入

```text
data/pubevent_soa_lite/events.jsonl
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl
```

#### 输出

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/final_audit.json
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/gold_manifest.json
```

#### Manifest 建议命令

```bash
python scripts/write_gold_manifest.py \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --version "v3_repaired_plus_low37_gold_final" \
  --quality-status data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/final_audit.json
```

#### 当前状态

Gold 数据本身已经 ready。需要确认 `gold_manifest.json` 是否已经写入并纳入最终 release 目录。如果没有，应补写 manifest。

---

### G. Benchmark Task Construction

#### 目标

从 gold release 构造三个 benchmark task：

```text
1. tuple_identification
2. evidence_support_classification
3. chain_construction
```

#### 输入

```text
data/pubevent_soa_lite/events.jsonl
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl
```

#### 主要脚本

```text
scripts/build_benchmark_tasks.py
```

#### 推荐命令

```bash
python scripts/build_benchmark_tasks.py \
  --events data/pubevent_soa_lite/events.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --output-dir data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold \
  --negative-per-tuple 2 \
  --max-text-chars 1500 \
  --seed 42 \
  --make-splits
```

#### 输出目录

```text
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/
```

#### 输出文件

```text
tuple_identification.jsonl
evidence_support_classification.jsonl
chain_construction.jsonl
benchmark_statistics.json
benchmark_manifest.json
splits/train/tuple_identification.jsonl
splits/train/evidence_support_classification.jsonl
splits/train/chain_construction.jsonl
splits/dev/tuple_identification.jsonl
splits/dev/evidence_support_classification.jsonl
splits/dev/chain_construction.jsonl
splits/test/tuple_identification.jsonl
splits/test/evidence_support_classification.jsonl
splits/test/chain_construction.jsonl
```

#### 当前状态

已完成 benchmark task construction，并已通过 sanity audit。

已确认统计：

```text
Events:                         50
Evidence:                       1767
Gold tuples:                    188
Gold chains:                    138

tuple_identification rows:      50
evidence_support rows:          736
chain_construction rows:        50

missing tuple evidence refs:    0
missing chain evidence refs:    0

train/dev/test events:          40 / 5 / 5
train ∩ dev:                    0
train ∩ test:                   0
dev ∩ test:                     0

evidence_support labels:
  supported:                    334
  not_enough_info:              376
  partially_supported:          26

evidence_support sample types:
  positive:                     360
  negative_same_event:          376

chains containing '?':          []
bad chain count:                0
```

---

### H. Model Experiment / Ablation / Evaluation / Paper Tables

#### 目标

使用 benchmark 或 paper pipeline 完成模型实验、消融实验、评估表格和案例分析。

#### 输入

两类输入可能并行存在：

第一类：paper pipeline 输入

```text
configs/paper.yaml
configs/ablation.yaml
data/pubevent_soa_lite/events.jsonl
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
gold tuples/chains
```

第二类：benchmark task 输入

```text
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/tuple_identification.jsonl
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/evidence_support_classification.jsonl
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/chain_construction.jsonl
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/splits/
```

#### README 中已有实验命令

```bash
python scripts/run_paper_experiment.py --config configs/paper.yaml
python scripts/run_ablation.py --config configs/ablation.yaml
```

#### 预期输出

```text
outputs/runs/{run_id}/config.yaml
outputs/runs/{run_id}/predictions.jsonl
outputs/runs/{run_id}/candidate_soa_tuples.jsonl
outputs/runs/{run_id}/verified_soa_tuples.jsonl
outputs/runs/{run_id}/metrics.json
outputs/runs/{run_id}/summary.json
outputs/runs/{run_id}/main_results.csv
outputs/runs/{run_id}/ablation_results.csv
outputs/runs/{run_id}/retrieval_results.csv
outputs/runs/{run_id}/verifier_results.csv
outputs/runs/{run_id}/human_eval_sheet.csv
outputs/runs/{run_id}/case_studies.jsonl
```

#### 当前状态

尚未完成正式模型实验、消融实验和论文结果表格。

下一阶段应该优先完成：

```text
1. 明确 benchmark evaluation protocol
2. 跑通 baseline / EpiSOA / ablation
3. 输出 main results、ablation results、retrieval/verifier results
4. 生成论文表格和案例分析
```

---

## 4. 当前完成阶段总结

### 按 README 5 步流程

```text
1. Formal event registry construction              已完成
2. Evidence collection with C-FSM                  已完成
3. Evidence normalization and annotation sheet     已完成
4. LLM preannotation, human review, gold export    已完成
5. Experiment execution and evaluation             部分完成
   - benchmark task construction 已完成
   - benchmark sanity audit 已完成
   - model experiment / ablation 尚未完成
```

### 按实际 8 环节流程

```text
A. Formal Event Registry                           已完成
B. C-FSM Evidence Collection                       已完成
C. Evidence Cleaning / Normalization               已完成
D. Annotation Input Construction                   已完成
E. LLM Pre-annotation + Human Verification         已完成
F. Gold Tuple / Gold Event Chain Release           基本完成，需确认 manifest
G. Benchmark Task Construction                     已完成
H. Model Experiment / Ablation / Evaluation        未完成
```

简化判断：

```text
数据构建主线：基本完成
Benchmark 构建：已完成
论文实验主线：尚未完成
论文写作主线：尚未完成结果章节、实验章节和方法对齐
```

---

## 5. 当前最重要的 canonical 文件清单

### 5.1 事件注册表

```text
data/pubevent_soa_lite/events.jsonl
```

用途：全部 pipeline 的起点。

### 5.2 Evidence canonical 文件

```text
data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl
```

用途：gold audit、benchmark construction、paper experiment 的正式证据文件。

不要替换为：

```text
data/pubevent_soa_lite/evidence_filtered.jsonl
```

### 5.3 Gold tuple 文件

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl
```

用途：tuple identification gold output、evidence support classification tuple claims、evaluation ground truth。

### 5.4 Gold chain 文件

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl
```

用途：chain construction gold output、event-chain-based SOA attribution、case study。

### 5.5 Gold audit / manifest

```text
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/final_audit.json
data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/gold_manifest.json
```

用途：论文数据质量证明、release metadata。

### 5.6 Benchmark 输出

```text
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/tuple_identification.jsonl
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/evidence_support_classification.jsonl
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/chain_construction.jsonl
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/benchmark_statistics.json
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/benchmark_manifest.json
data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/splits/
```

用途：后续模型实验、baselines、ablation 和 leaderboard-style evaluation。

---

## 6. 建议 Claude Code 下一步执行清单

### Step 1：只读盘点当前文件是否存在

```bash
python - <<'PY'
from pathlib import Path

paths = [
    "data/pubevent_soa_lite/events.jsonl",
    "data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl",
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl",
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl",
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/final_audit.json",
    "data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/gold_manifest.json",
    "data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/tuple_identification.jsonl",
    "data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/evidence_support_classification.jsonl",
    "data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/chain_construction.jsonl",
    "data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/benchmark_statistics.json",
    "data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/benchmark_manifest.json",
]

for p in paths:
    path = Path(p)
    print(f"{'OK' if path.exists() else 'MISSING'}  {p}")
PY
```

### Step 2：复查 gold audit

```bash
python scripts/audit_gold_annotation.py \
  --events data/pubevent_soa_lite/events.jsonl \
  --evidence data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl \
  --tuples data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl \
  --chains data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl \
  --output data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/final_audit.json
```

预期：

```text
Total issues: 0
ready_for_final_gold: true
```

### Step 3：确认 benchmark statistics

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path("data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/benchmark_statistics.json")
obj = json.loads(p.read_text(encoding="utf-8"))
print(json.dumps(obj, ensure_ascii=False, indent=2))
PY
```

重点确认：

```text
input_counts.events = 50
input_counts.evidence = 1767
input_counts.tuples = 188
input_counts.chains = 138
validation.missing_tuple_evidence_refs_count = 0
validation.missing_chain_evidence_refs_count = 0
```

### Step 4：补齐 benchmark evaluation harness

当前已经有 benchmark task 文件，但还需要正式实验评估脚本。建议新增或检查：

```text
scripts/run_benchmark_eval.py
scripts/run_benchmark_baselines.py
scripts/audit_benchmark_tasks.py
scripts/export_paper_tables.py
```

建议输出：

```text
outputs/benchmark_runs/{run_id}/
|-- config.yaml
|-- tuple_identification_predictions.jsonl
|-- evidence_support_predictions.jsonl
|-- chain_construction_predictions.jsonl
|-- metrics.json
|-- main_results.csv
|-- ablation_results.csv
|-- error_analysis.jsonl
`-- case_studies.jsonl
```

### Step 5：设计实验组

至少应包含：

```text
Baseline 1: direct LLM without evidence chain
Baseline 2: evidence retrieval + direct tuple generation
Baseline 3: chain retrieval without verifier
EpiSOA full: event-chain retrieval + SOA tuple generation + evidence verifier
Ablation A: w/o event chain
Ablation B: w/o source balance
Ablation C: w/o verifier
Ablation D: w/o repair/coverage-aware evidence
```

### Step 6：生成论文结果表

建议最终形成：

```text
Table 1 Dataset statistics
Table 2 Source type distribution
Table 3 Benchmark task statistics
Table 4 Main results
Table 5 Ablation results
Table 6 Evidence support classification results
Table 7 Chain construction/retrieval results
Table 8 Human/LLM agreement or verification quality
Figure 1 Overall framework
Figure 2 Data construction pipeline
Figure 3 Evidence coverage distribution
Figure 4 Case study event-chain visualization
```

---

## 7. Claude Code 推荐工作顺序

当前不要回头重跑采集；应从实验与论文输出推进：

```text
1. 只读确认 canonical 文件
2. 复跑 gold audit，确保仍然 0 issue
3. 复查 benchmark statistics 和 splits
4. 若缺 gold_manifest，则补写
5. 新建 benchmark evaluation harness
6. 跑最小 baseline：direct LLM / rule baseline
7. 跑 EpiSOA full pipeline
8. 跑 ablation
9. 导出 paper tables
10. 写 method / dataset / experiment / case study 章节
```

---

## 8. 给 Claude Code 的短提示词

可以直接复制给 Claude Code：

```text
你正在接手 EpiSOA 论文项目。不要重置 workspace，不要使用 evidence_filtered.jsonl，不要重跑全量采集。当前 canonical evidence 是 data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl；当前 gold 目录是 data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/；当前 benchmark 目录是 data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/。

项目已经完成 50 events、1767 evidence、188 gold tuples、138 gold chains；gold audit 0 issue 且 ready_for_final_gold=true；benchmark 三个任务已构建：tuple_identification 50 rows、evidence_support_classification 736 rows、chain_construction 50 rows，train/dev/test=40/5/5 且无重叠。

下一步请只读检查这些 canonical 文件是否存在，复查 final_audit 和 benchmark_statistics，然后补齐 benchmark evaluation harness、baseline、ablation、paper table export。所有修改必须小步提交；涉及 gold/evidence 的写操作必须先 dry-run、再备份、再 audit。
```

---

## 9. 项目当前结论

EpiSOA 当前已经不是“准备进入 gold 标注阶段”，而是已经完成了：

```text
事件注册
证据采集
证据修复
证据清洗
LLM gold annotation
人工/脚本审计修复
gold release
benchmark task construction
benchmark sanity audit
```

尚未完成的核心是：

```text
正式实验
baseline 对比
消融实验
结果表格
案例分析
论文写作与投稿包装
```

因此后续 Claude Code 的任务重心应从 **data construction** 转向 **benchmark evaluation + paper production**。
