# EpiSOA 项目流程、LLM 节点与模型路线

## 当前阶段

当前主线已经进入 `silver_v1` / `human_gold_v1` 人工裁决阶段。`llm_gold_tuples.jsonl` 和 `llm_gold_event_chains.jsonl` 只作为 LLM 预标注银集使用，不能直接当作论文实验的最终 gold。

当前阻塞点是 pilot 人工审核：先完成 `human_tuple_adjudication_sheet_pilot5.csv` 和 `human_chain_adjudication_sheet_pilot5.csv` 中 E015、E049、E020、E050、E002 的 `review_decision` 与修订字段，再转全量 human gold。

## 流程总览

1. Event registry：人工筛选事件，`scripts/validate_events.py` 校验；不需要 LLM。
2. Evidence collection：`scripts/collect_evidence.py` 使用搜索 API、规则规划、C-FSM repair；不需要 LLM。
3. Normalize / sheet：`scripts/normalize_evidence.py`、`scripts/make_annotation_sheet.py`；不需要 LLM，建议人工抽查。
4. LLM preannotation：`scripts/run_llm_gold_preannotation.py` 生成 tuple / chain silver；需要高质量中文抽取和严格 JSON Schema 输出。
5. Human adjudication：`scripts/export_silver_benchmark.py`、`scripts/build_human_adjudication_sheet.py` 后人工裁决 `accept/revise/drop/add_missing`；这是当前最关键节点。
6. Human gold export：`scripts/convert_adjudication_to_human_gold.py`、`scripts/audit_human_gold.py`、`scripts/validate_gold_dataset.py`；主要是程序校验，失败项人工修正。
7. Paper / ablation：`scripts/run_paper_experiment.py`、`scripts/run_ablation.py`；LLM 用于 schema attribution 和 faithfulness verifier，图构建、检索和证据排序仍是规则逻辑。
8. Benchmark / model probe：`scripts/run_benchmark_eval.py`、`scripts/run_model_capability_probe.py`；LLM 用于任务预测和可选 LLM-as-judge。

## LLM 使用点

| 节点 | 入口 | 当前用途 | 模型要求 |
| --- | --- | --- | --- |
| Preannotation | `scripts/run_llm_gold_preannotation.py` | 生成 tuple 与 event chain silver | 中文抽取强、证据约束强、严格 JSON Schema |
| Annotation expansion | `scripts/run_annotation_expansion.py` | 扩展 tuple / chain 候选 | 同上，适合小批量质量优先 |
| Schema attribution | `src/episoa/attribution/schema_attributor.py` | 从事件链和证据生成 SOA tuple | 严格结构化输出、可解释 rationale |
| Faithfulness verifier | `src/episoa/verifier/faithfulness_verifier.py` (pipeline); `src/episoa/verification/faithfulness_verifier.py` (scripts/tests) | 判断 tuple 是否被证据支持 | 证据忠实性判断、保守输出 |
| Benchmark eval | `src/episoa/evaluation/benchmark_runner.py` | tuple identification / evidence support / chain construction | 结构化预测、可比较指标 |
| LLM judge | `src/episoa/evaluation/benchmark_metrics.py` | 可选语义等价裁判 | 稳定 JSON、低幻觉 |

## 人工审核点

| 阶段 | 文件 | 人工动作 |
| --- | --- | --- |
| Event registry | `data/pubevent_soa_lite/events.jsonl` | 只保留具体、公开、可证据化事件 |
| Evidence sheet | annotation sheet 输出 | 抽查证据质量、source type、coverage |
| Pilot adjudication | `data/pubevent_soa_lite/human_gold_v1/*pilot5.csv` | 对 5 个 pilot 事件做 `accept/revise/drop/add_missing` |
| Full adjudication | `data/pubevent_soa_lite/human_gold_v1/*full.csv` | pilot 通过后裁决全量 tuple / chain |
| Gold audit failures | human gold audit / validate 报告 | 修正不合法 label、缺证据、chain 覆盖错误 |

### Uncertainty-driven adjudication

`adjudication_priority_score`、`priority_bucket`、`priority_reason` 只用于 full / pilot adjudication sheet 的审核排序与风险提示。它们不会自动改写 `review_decision`，也不会影响 `convert_adjudication_to_human_gold.py` 的 gold 生成规则；所有进入 human gold 的记录仍必须由人工明确 `accept`、`revise` 或 `add_missing` 并通过 audit。

## 模型路线

默认质量优先路线已切到 `deepseek-v4-flash`（DeepSeek-V4 官方正式模型，非即将弃用的 `deepseek-chat` 别名）：`configs/paper.yaml`、`configs/ablation.yaml`、`configs/ablation_human_gold_v2.yaml` 主实验统一使用 DeepSeek 官方 endpoint `https://api.deepseek.com`，通过 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 环境变量鉴权。

`deepseek-chat` 与 `deepseek-reasoner` 为 legacy 别名，将于 2026/07/24 15:59 UTC 彻底退役，不再用于主实验。过渡期内 `deepseek-chat` 透明路由到 `deepseek-v4-flash` 非思考模式，但论文实验直接使用正式模型名 `deepseek-v4-flash` 以保证可复现性。

DeepSeek-V4 默认开启 thinking mode，会静默忽略 `temperature` 并消耗 token 预算生成 CoT。主实验配置统一显式设置 `thinking_mode: "disabled"`（由 `src/episoa/llm/client.py` 透传为 payload 顶层 `thinking: {"type": "disabled"}`），使 `temperature: 0.1` 生效、输出直接为结构化 JSON、成本与延迟可控。probe 对比评估保留各模型默认 thinking 行为，不设此项。

`gpt-5.5` 保留为模型 probe 中的强模型对照项，便于在同一 probe 中比较 `deepseek-v4-flash` 与 `gpt-5.5` 的 parse success、zero prediction count、Tuple-F1-soft、sentiment accuracy、成本和延迟。

LLM 调用支持两种 `response_format` 模式，由 model 配置的 `response_format_mode` 字段控制：`json_schema`（默认，OpenAI 原生，API 层强制 schema）和 `json_object`（DeepSeek V4 等 only-json_object provider，client 自动把 `json_schema` 降级为 `json_object` 并把 schema 注入 system_prompt）。主实验配置统一设置 `response_format_mode: "json_object"`。provider 不支持时 client 仍会按降级逻辑去掉 `response_format` 后重试。

## 下一步命令

完成 pilot sheet 后运行：

```bash
python scripts/convert_adjudication_to_human_gold.py --pilot
python scripts/audit_human_gold.py --pilot
```

pilot 通过后再做全量 188 tuple / 138 chain，生成正式 human gold，再运行模型 probe 和 human-gold ablation。
