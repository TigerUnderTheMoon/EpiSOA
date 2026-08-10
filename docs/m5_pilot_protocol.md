# EpiSOA-EA M5六事件Pilot协议

版本：`m5-pilot-protocol-v1`
方法冻结候选：`EpiSOA-EA-v1.5-prepilot`
证据等级：diagnostic / internal decision，不作为论文性能证据
状态：协议与事件已冻结；Document收集、人工Gold和真实API尚未开始

## 1. 目的与可证伪问题

M5只回答以下问题：v1.5能否在六类真实公共事件中无损表达来源级Effect、Claim和Evidence，并通过APCF保守融合为可追溯Dossier？

主要假设：冻结Schema能够覆盖绝大多数Gold记录；Evidence gate不会系统性接受无证据Claim；APCF不会违反hard constraint或complete-link；Dossier能够完整回读到Document、Source和Span。

替代解释包括：错误来自文档抽取而非Fusion；blocking遗漏限制Fusion上限；隐式AttributionHolder缺少surface导致Gold边界不稳定；来源谱系误判造成独立来源过计数。

结构性证伪条件：真实Gold无法稳定映射Schema；同类情况需要新增关系或主体类别才能表达；APCF在满足现有规则时仍系统性错误合并；provenance无法由现有数据契约完整表达。发生任一情况时进入`METHOD REVISION`，不得以Prompt调优掩盖。

## 2. 冻结与变更控制

冻结对象包括：Git tag、实现commit、Schema版本、Prompt版本、配置、模型及解码设置、事件登记表、公平性Manifest、评价代码和门禁。

M5开始后禁止静默修改。所有问题先写入`docs/m5_change_log.md`，记录发现时间、事件、复现材料、影响层、严重度和处置决定。

允许的`PASS WITH PATCH`仅限：确定性bug、Schema文字澄清、不会改变任务含义的Prompt修正、错误日志或工具可用性修复。任何主体类别、Effect类型、关系类型、APCF结构或评价定义改变都属于`METHOD REVISION`并升级版本。

## 3. 事件与Document

事件固定在`configs/ea_pilot_events.yaml`。每领域一个，共六个；采用criterion-based purposive sampling与maximum variation sampling。Pilot不追求总体代表性，只覆盖边界条件。

每个事件保留6–8篇有效Document，总量36–48篇。最低要求：

- 至少3个不同、可确认的`primary_source_id`；
- 至少一份原始/官方材料；
- 至少一份独立报道或公开互动材料；
- 同一转载谱系不得伪装成多个独立来源；
- 全文必须公开可访问、可合法保存研究副本并冻结`normalized_text`与`content_hash`；
- 摘要、搜索片段和登录后私密内容不得冒充正文。

在任何模型推理前完成Document审计。只有网页失效、正文不可得或无法达到最低来源谱系要求时才允许替换事件；替换必须发生在模型推理前并写入change log，不能依据模型表现替换。

## 4. Gold顺序与职责

Gold严格按以下顺序完成：

```text
Document freeze
→ A/B source-level Effect + Evidence
→ A/B source-level Claim + Evidence
→ C document-level disagreement adjudication
→ automatic Canonical Effect proposal
→ A/B Fusion Pair annotation
→ C only for Fusion disagreement / needs_adjudication
→ Gold membership and Dossier audit
```

A/B不得填写Canonical ID。LLM预标注只能以`candidate_origin=llm_or_pipeline_candidate`出现，每行必须由人类显式`accept/revise/reject/add`。两位标注员都可用`add`从冻结Document新增Gold记录，避免候选召回限制Gold上限。

Fusion Gold重点区分：应合并但未合并、不应合并但被合并、标注者无法可靠判断。第三类保留`unresolved`或`needs_adjudication`，不得强制造出确定标签。

## 5. 首次真实Pipeline运行

第一次真实运行只执行EpiSOA-EA，不运行五方法主比较或消融：

```text
python -m episoa.cli prepare-ea --config configs/ea_pilot.yaml
python -m episoa.cli run-ea --config configs/ea_pilot.yaml --stage m2
python -m episoa.cli run-ea --config configs/ea_pilot.yaml --stage m3
python -m episoa.cli run-ea --config configs/ea_pilot.yaml --stage fusion --fusion-method apcf
python -m episoa.cli run-ea --config configs/ea_pilot.yaml --stage dossier
```

运行前必须确认配置、commit、tag、事件登记hash、Document manifest、Prompt hash、模型响应中的实际model字段和公平性Manifest一致。禁止静默截断或跨Document混入正文。

为了验证结构确定性，在不改变输入、模型输出缓存和配置的条件下重复运行确定性后处理两次；比较Canonical membership、ID、Dossier hash和序列化顺序。不是要求远程LLM生成文本逐字一致。

## 6. 工程硬门禁

以下条件必须全部满足：

| 门禁 | 要求 |
|---|---:|
| Effect Candidate Blocking Recall | ≥ 0.98 |
| Claim Candidate Blocking Recall | ≥ 0.98 |
| Dossier provenance回读成功率 | 1.00 |
| membership-based ID确定性 | 1.00 |
| 缓存固定后的结构重复运行一致性 | 1.00 |
| complete-link violation | 0 |
| hard-constraint violation | 0 |
| Span回读`normalized_text`成功率 | 1.00 |
| `content_hash`校验成功率 | 1.00 |
| 确定性转载测试Source Independence Overcount | 0 |
| Gold循环依赖 | 0 |

Gold无法映射Schema的记录必须逐条报告。目标是0；任何非零值都必须先判断是标注错误、文字澄清还是结构性Schema缺口。

## 7. 描述性指标

Effect F1、Claim F1、Relation Decision Macro-F1、Fusion Pairwise F1、Canonical cluster F1、Unsupported Claim Rate、Holder mismatch、False Merge和False Split只用于发现异常，不作为六事件论文结论，也不因数值不够漂亮而修改方法。

Conflict Preservation没有足够Gold contradiction pair时记为`NA`并报告样本数。未裁决pair不进入Canonical P/R/F1分母，但必须报告数量和覆盖率。

## 8. 运行矩阵与预算

| Run ID | 内容 | 固定项 | 输出 | 状态 |
|---|---|---|---|---|
| M5-GOLD | A/B/C来源级与Fusion Gold | Document、规范、模板 | Gold + IAA + blocking audit | planned |
| M5-EA-01 | 首次完整EA真实运行 | model/config/prompt/events | M2/M3/APCF/Dossier | blocked by Gold and Documents |
| M5-DET-01 | 缓存固定后的确定性复跑 | 所有输入及缓存 | membership/hash diff | blocked by M5-EA-01 |
| M5-REVIEW | 六事件门禁评审 | Gold与两次结构输出 | PASS/PATCH/REVISION记录 | blocked |

Pilot上限为6个事件、每事件6–8篇Document、最多48篇Document。首次门禁通过前不运行主比较方法和六项消融，不扩充事件，也不启动60-event Formal流程。

## 9. 评审决定

- `PASS`：全部工程硬门禁通过，无结构性Schema/APCF缺陷；进入60 Formal Event选择与Gold计划。
- `PASS WITH PATCH`：硬门禁失败可归因于局部bug、文字澄清或Prompt边界，修复后必须更新patch版本并重新运行全部六事件受影响阶段。
- `METHOD REVISION`：需要改变任务定义、Schema核心字段、APCF主体结构、关系/主体类别或评价口径；升级v1.6并重新冻结独立Pilot。

不得因为F1偏低而自动选择后两类决定；决定依据是设计正确性、可表达性、可追溯性和规则一致性。

## 10. Legacy回归记录

当前3项non-EA legacy regression因缺少gitignored historical fixtures不可运行：

```text
tests/test_data_io.py::test_validate_paper_data_defaults_to_human_gold_v2
tests/test_data_io.py::test_validate_paper_data_script_uses_checkout_package
tests/test_manuscript_builder.py::test_supporting_data_package_contains_manifest_and_omits_raw_fulltext
```

状态固定为`non-EA legacy regression unavailable due to missing ignored historical fixtures`。不得伪造历史数据使其假通过；该状态不等于测试通过，也不阻断EA Pilot工程门禁。
