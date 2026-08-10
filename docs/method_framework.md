# EpiSOA-EA 最终论文方法框架（冻结版）

版本：1.5
状态：本文档定义冻结的论文目标架构。`src/episoa/ea/`已实现v1.5离线Schema、M3/Fusion/Dossier阶段隔离、APCF、Fusion Gold/评价接口、Long-context容量门禁及合成测试；六事件M5 Pilot、真实API运行、正式Gold与论文实验仍未执行，不得将代码就绪表述为实证完成。
配套标注规范：[`annotation_guidelines.md`](annotation_guidelines.md)

## 1. 方法名称与论文定位

中文名称：**大模型辅助的利益相关者观点成因归属与字段级证据验证框架**。

英文名称：**EpiSOA-EA: Stakeholder-Centered Explanatory Attribution with Field-Level Evidence Grounding**。

本研究的实际应用对象是**一个具体的多来源公共事件**。EpiSOA-EA不是对一批事件分别做一次浅层分类，而是针对单个事件中的多篇新闻、官方材料、公共互动及其他异质来源文档，完成深度信息组织：

1. 谁在什么阶段针对什么对象表达了何种立场、情绪或行动；
2. 文本使用什么解释说明该立场、情绪或行动；
3. 谁提出该解释，哪个来源报道该解释；
4. 哪些原文片段支持每个结构化字段；
5. 不同来源中的解释是等价、补充、明确矛盾还是暂时无法判断；
6. 如何将上述结果组织为可查询、可追溯、可审计的事件观点档案。

最终应用产物是**Event Dossier（事件观点档案）**，其正式信息组织模型是**Event Opinion Graph**。60个Formal Event构成用于验证该方法能否跨不同治理情境稳定工作的Benchmark corpus；它们不是60个需要在论文中逐一解释的最终研究对象。真正的使用单位始终是一个具体的多来源公共事件。

本研究处理的是**文本表达的观点成因归属**，不是现实世界中的客观因果识别。它不估计处理效应，不作反事实推断，不裁决真实责任，也不构建一般事件因果图。

## 2. 研究问题

核心问题表述为：

> Given multiple heterogeneous documents about a public event, how can dispersed stakeholder viewpoints and explanatory attributions be transformed into a provenance-aware and evidence-grounded event dossier?

论文围绕以下研究问题展开：

- **RQ1：** EpiSOA-EA能否准确识别并验证来源级Stakeholder Effect和Explanatory Attribution？
- **RQ2：** 相对于直接读取同一事件全部文档的Long-context Event-level LLM，Document-level decomposition能否减少主体归属错误、跨文档污染和无依据Claim，同时保持可接受的抽取准确率？
- **RQ3：** CanonicalEffect、CanonicalClaimGroup和provenance-aware integration能否将来源级结果组织成一致且可追溯的Event Dossier？
- **RQ4：** Event Dossier能否降低人工定位来源、核查解释和理解多主体观点结构的成本？RQ4优先使用已经冻结的审计正确率、审计时间、证据定位和来源追溯指标回答，不新增复杂用户实验，除非现有指标经Pilot验证确实无法回答。

## 3. 核心输出与关系集合

### 3.1 Event Dossier与基本输出

最终正式输出是Event Dossier / Event Opinion Graph，而不是彼此孤立的若干JSONL记录。一个Event Dossier必须完整组织：

```text
Event
Stage
Document
Source
Effect
CanonicalEffect
AttributionClaim
CanonicalClaimGroup
ClaimPairRelation
EvidenceSpan
```

并保存以下可理解、可规范化和可追溯属性：

```text
holder_surface
holder_role
stakeholder_category

attribution_holder_surface
attribution_holder_role
attribution_holder_category

effect_type
effect_surface
effect_value
target

explanation_surface
normalized_explanation

relation_type
explicitness
certainty
polarity

document_id
reporting_source_id
primary_source_id
derivation_type
Evidence Span
```

**JSONL是Event Dossier的序列化存储形式；Event Opinion Graph是正式的事件级知识组织结构。** 每个JSONL记录仍保留其来源级身份和字段证据，事件级图结构负责连接这些记录，而不是用一条汇总标签替代它们。

`Effect`是一个原子化的观点或行动对象，类型只能是：

```text
stance
emotion
action
```

### 3.2 正式关系

主任务只包含三种成因归属关系：

| Effect类型 | 关系类型 | 含义 |
|---|---|---|
| `stance` | `stance_rationale` | 文本提出某立场的理由 |
| `emotion` | `emotion_trigger` | 文本提出某情绪的触发因素 |
| `action` | `action_motivation` | 文本提出某行动的动机 |

`no_relation`只用于候选关系判断和Relation Decision Macro-F1评价，不进入正式Claim表。

### 3.3 明确排除的任务

以下内容不属于本方法：

- 一般`event_cause`抽取；
- 客观因果效应或反事实推断；
- 无主体限定的“事件A导致事件B”；
- 现实责任认定；
- 责任框架分类；
- 复杂因果图学习；
- 将时间先后直接当作因果证据。

## 4. 三类角色与统一主体类别

方法必须区分：

- **EffectHolder：** 持有立场、产生情绪或实施行动的主体；
- **AttributionHolder：** 提出相关解释的主体；
- **ReportingSource：** 记录、转述或发布该解释的来源。

EffectHolder和AttributionHolder均以**抽象利益相关者类别**表示，而不是以具体人物级实体作为论文主任务。二者使用同一受控分类空间：

```text
government
public_institution
enterprise
affected_public
social_organization
expert
media
general_public
other_or_unknown
```

| 类别 | 定义 |
|---|---|
| `government` | 政府、监管部门、行政机关、街道、公安等政府治理主体 |
| `public_institution` | 学校、医院、高校、事业单位以及公共服务机构 |
| `enterprise` | 开发商、物业公司、平台企业、商家、生产经营企业等 |
| `affected_public` | 与事件利益直接相关或直接受到影响的公众，如居民、业主、家长、患者、消费者、员工、乘客等 |
| `social_organization` | 业委会、协会、NGO、社区组织、行业组织等 |
| `expert` | 专家、学者、律师、医生、专业顾问、研究人员等专业人士 |
| `media` | 新闻媒体、记者、媒体机构等 |
| `general_public` | 与事件没有直接利益关系的一般公众、网民、普通评论者等 |
| `other_or_unknown` | 确实存在但无法归入上述类别，或现有证据无法可靠判断的主体 |

EffectHolder必须同时保存`holder_surface`、`holder_role`和`stakeholder_category`；AttributionHolder必须同时保存`attribution_holder_surface`、`attribution_holder_role`和`attribution_holder_category`。其中：

> **surface用于人类理解和来源追溯；category用于规范化、归并和评价。**

例如：

```text
holder_surface = "3号楼业主王先生"
holder_role = "业主"
stakeholder_category = "affected_public"

attribution_holder_surface = "街道办相关负责人"
attribution_holder_role = "街道办"
attribution_holder_category = "government"
```

`holder_role`和`attribution_holder_role`保留“业主”“家长”“街道办”等角色表述，surface字段保留文档中的具体主体称谓，category字段进入统一标签空间。surface与role不要求跨文档严格归一，也不进入主要类别F1。增加surface字段不等于重新引入人物级任务：具体人名或组织名称不要求跨文档消歧，系统不建立复杂的人物级实体解析或跨文档实体归并。

不能因为某媒体发布了文档，就把该媒体自动视为AttributionHolder。转述结构中，原始说话者是AttributionHolder，当前发布机构是ReportingSource。

ReportingSource统一引用独立的`sources.jsonl`，不与EffectHolder或AttributionHolder类别混用。来源记录至少包含`source_id`、`source_name`和`source_type`，并保持具体来源级追踪。

## 5. 总体方法流程

```text
Multiple Documents of One Event
  -> Document-level Semantic Extraction
  -> Field-level Evidence Verification
  -> Verified Source-level Effects & Claims
  -> APCF: Attribution-aware Cross-document Fusion
  -> Canonical Effects & Canonical Claim Groups
  -> Event Opinion Graph
  -> Event Dossier
```

Document-level extraction、字段级验证、APCF和Dossier物化共同构成论文的三级核心架构。`run-ea --stage m3`停止于verified source-level records；`run-ea --stage fusion`才执行Canonical融合；`run-ea --stage dossier`只物化事件档案。该隔离用于分别定位文档理解错误、融合错误和档案组织错误。

## 6. 阶段0：事件、文档与来源规范化

### 6.0 抽取与分析粒度

**抽取单位是文档，分析单位是事件。** EpiSOA-EA逐篇处理新闻、网页或其他来源文档。每篇Document独立产生0–N条Effect、0–N条Attribution Claim和0–N条Evidence Link；没有相应表达时允许产生0条，存在多个主体、立场、情绪、行动或解释时必须原子化为多条。不得把“每篇Document产生一个输出”作为设计假设，也不把同一事件的全部文档直接拼接后一次性交给LLM生成事件级结构。

> EpiSOA-EA adopts document-level extraction and event-level aggregation. Source-specific Effects and Claims are first extracted and grounded within individual documents, and are subsequently normalized and aggregated within the same event for cross-source analysis.

每条来源级Effect和Claim必须保留`document_id`、`reporting_source_id`、字段级Evidence Span，以及可由文档/Claim记录追溯的来源继承信息。单篇文档抽取完成后，才在相同`event_id`内进行主体类别归一、Effect归并/去重、Canonical Claim归并、Claim Pair关系判断及来源支持、补充和矛盾分析。该原则用于防止不同来源间的主体与解释归属污染，保持EffectHolder、AttributionHolder和ReportingSource可区分，并保证所有事件级结论可回溯至具体文档和证据片段。

该阶段完成：

1. 建立正式事件登记表；
2. 固化文档正文并计算`content_hash`；
3. 文档去重和近重复检测；
4. 保存发布时间、父文档和首要来源；
5. 通过`primary_source_id`记录信息来源谱系，并保留文档内容继承方式。

### 6.1 内容继承

`derivation_type`描述文档内容如何继承：

```text
original
official_republication
syndicated_copy
quoted_from_other_source
synthesized_from_multiple_sources
unknown
```

### 6.2 来源谱系与Multiplicity

v1.5不建立Claim级`independent/partially_independent/dependent/undetermined`变量。`primary_source_id`承担来源谱系去重职责，`derivation_type`记录`original`、`independent_report`、转载、再发布、依赖性转引或`unknown`。Dossier只派生：`document_multiplicity`、`primary_source_multiplicity`、`dependent_reproduction_count`和`unknown_lineage_count`。未知谱系不得默认按独立来源累计，网页数量不得直接解释为独立印证数量。

## 7. 阶段1：原子Viewpoint Effect发现

该阶段使用高召回的大模型辅助抽取发现Effect候选。每条Effect只能包含：

```text
一个EffectHolder
一个EffectType
一个EffectValue
一个Target
一个EffectStage
```

“居民反对方案并拒绝签约”必须拆为一个Stance和一个Action，不能压缩为一条混合记录。每个字段均应关联原文Evidence Span。

每条来源级Effect同时保存：

```text
document_id          # 当前Effect所在文档
reporting_source_id  # 当前文档的发布来源
primary_source_id    # 来源继承链中的首要来源
derivation_type      # 当前文档的内容继承方式
stakeholder_category # EffectHolder的九类受控标签
holder_surface       # 原文中的具体EffectHolder称谓
holder_role          # 原始角色展示字段
effect_surface       # 原文中的立场、情绪或行动表述
effect_value         # 规范化后的Effect值
```

Stance的`effect_value`固定为：

```text
support
oppose
question
neutral
uncertain
```

其中`support`表示明确支持、赞同、接受或认可；`oppose`表示明确反对、拒绝或不接受；`question`表示质疑目标、真实性、合理性、程序或解释但尚不足以判为明确反对；`neutral`表示文本确实表达立场，但明确中立或无明显支持/反对倾向；`uncertain`表示文本确实存在立场表达，但现有证据不足以可靠判断其类别。文本没有表达对应立场时，不创建Stance Effect；`uncertain`不能用于表示“没有立场字段”。语义等价的“不接受”“反对”“不同意”均规范为`oppose`。

Emotion的`effect_value`固定为：

```text
positive
negative
neutral
uncertain
```

其中`positive`表示满意、认可、欣慰、积极等总体正向情绪；`negative`表示不满、愤怒、担忧、失望、焦虑等总体负向情绪；`neutral`仅用于文本确实表达某种情绪状态、但该状态无明显正负极性；`uncertain`表示文本确实存在情绪表达，但无法根据证据可靠判断其极性。文本没有表达情绪时不创建Emotion Effect，纯事实陈述同样不创建Emotion Effect，不能标为`neutral`；`uncertain`不能用于表示“没有情绪字段”。不建立anger、fear、sadness等细粒度情绪分类任务。

Action的`effect_value`继续使用规范化短语，不强制建立跨事件统一Action类别体系。`effect_surface`及字段级Evidence Span保留原文措辞，`effect_value`用于封闭标签或短语规范化，二者不得相互替代。

来源级Effect示例：

```json
{
  "effect_id": "EF001",
  "event_id": "E001",
  "document_id": "D001",
  "reporting_source_id": "SRC001",
  "primary_source_id": "SRC001",
  "derivation_type": "original",
  "holder_surface": "3号楼业主王先生",
  "stakeholder_category": "affected_public",
  "holder_role": "业主",
  "effect_type": "stance",
  "effect_surface": "不接受现有补偿安置方案",
  "effect_value": "oppose",
  "target": "补偿安置方案",
  "effect_stage": "conflict"
}
```

Emotion记录使用相同结构，例如`effect_type="emotion"`、`effect_value="negative"`；具体“不满”“担忧”或“愤怒”等措辞保留在`effect_surface`及Evidence Span中。

每条来源级Effect具有`effect_id`。CanonicalEffect表示**类别级观点命题**，不是同一具体人物或组织的共指结果。以下字段是structural signature / compatibility dimensions，而不是要求字符串完全相同的复合主键：

```text
event_id：hard exact
stakeholder_category：hard exact
effect_type：hard exact
Stance/Emotion effect_value：closed-label hard exact
Action effect_value：semantic compatibility
Target：semantic compatibility
effect_stage：observation attribute
```

因此，“补偿方案/现行补偿安置方案”和开放Action短语可经冻结的语义pair judgment判为等价。Stage不参与Canonical身份；成员Effect保留各自Stage，CanonicalEffect派生`observed_stages`。只有明确时间语义冲突才阻止归并。同类别的“物业”“开发商”或不同具体主体可以共享类别级观点命题，但所有具体`holder_surface`始终保留在成员Effect中，论文不得称其为“同一主体归并”。`canonical_effect_id`按`event_id + sorted(member_effect_ids)`生成，不按结构字段直接哈希。歧义pair进入C裁决，不形成额外标注层。

同一个`stakeholder_category`在同一事件中可以对应多个不同CanonicalEffect，包括针对同一或不同Target的`support`、`oppose`和`question`。系统不得将同类主体的异质观点压缩为“公众总体立场”等单一汇总标签。

`effect_stage`表示Effect发生的事件阶段，不能由文档发布时间直接代替。

两类阶段字段共用受控标签：

```text
trigger
diffusion
conflict
response
resolution
follow_up
unknown
```

## 8. 阶段2：类型约束的Explanation Candidate构建

系统针对每个原子Effect构建解释候选。候选可来自：

```text
explicit_cue
argument_structure
cross_sentence
temporal_compatible
llm_proposed
```

候选必须满足以下基本约束：

```text
same_event
temporal_compatible
contextually_connected
type_compatible
participant_consistent
```

时间只用于排除不可能方向、提供上下文和构造负例，不能单独证明解释关系。大模型可以发现隐式候选，但不能脱离原文自由创造原因。

试标阶段不设置固定Top-K硬截断，以免在高召回候选阶段系统性漏掉少数类解释。单个Effect候选过多时采用分批关系判断；如正式实验确需候选上限，必须在查看测试结果前预注册K，并同时报告候选召回率。

## 9. 阶段3：双主体约束的归属关系判断

系统在统一候选集中判断Explanation是否用于解释目标Effect。候选决策为：

```text
supported
no_relation
```

关系类型由Effect类型唯一约束。系统还必须分别判断EffectHolder和AttributionHolder，并记录：

```text
explicitness: explicit / implicit
certainty: certain / uncertain
polarity: affirmed / denied
```

`claim_stage`表示解释被提出或报道时所处的事件阶段。它与`effect_stage`独立标注，不得因为Claim解释某个早期Effect，就自动令二者相同。

每条来源级Claim同时保存：

```text
document_id                   # 当前Claim所在文档
reporting_source_id           # 当前文档的发布来源
primary_source_id             # 来源继承链中的首要来源
attribution_holder_category   # 解释提出者的九类受控标签
attribution_holder_surface    # 原文中的具体解释提出者称谓；无明确surface时为null
attribution_holder_role       # 原始角色展示字段
explanation_surface       # 原文中的解释表述
normalized_explanation    # 规范化后的解释命题
```

前者用于评价原文抽取，后者用于关系判断和跨来源归并。

来源级Claim示例：

```json
{
  "claim_id": "CL001",
  "effect_id": "EF001",
  "document_id": "D001",
  "reporting_source_id": "SRC001",
  "primary_source_id": "SRC001",
  "derivation_type": "original",
  "explanation_surface": "补偿标准低于他们的预期",
  "normalized_explanation": "补偿标准低于预期",
  "relation_type": "stance_rationale",
  "attribution_holder_surface": "业主代表李女士",
  "attribution_holder_category": "affected_public",
  "attribution_holder_role": "业主代表",
  "claim_stage": "conflict",
  "explicitness": "explicit",
  "certainty": "certain",
  "polarity": "affirmed"
}
```

该Claim及其引用的Effect分别通过Evidence Link绑定当前文档中的字段级证据。

只有通过关系判断的候选才能形成正式Claim。正式Claim表不保存恒定的`relation_decision=supported`字段；`supported/no_relation`保留在运行过程文件中。

## 10. 阶段4–6：字段级证据验证、APCF与Dossier物化

### 10.1 分离式证据验证

验证器只接收Effect、Explanation、关系类型、相关主体和原文证据，不接收生成器的推理过程。若生成器与验证器使用相同底层模型，应称为**separated evidence verifier**，不能称为完全独立验证器。

验证字段包括：

```text
effect_grounded
explanation_grounded
relation_grounded
direction_correct
effect_holder_grounded
attribution_holder_grounded
certainty_correct
polarity_correct
```

验证状态为：

```text
verified
insufficient
rejected
```

**`verified`仅表示原文确实支持“某主体提出了该解释”，不表示该解释是现实世界中的真实原因。**

所有验证尝试及其`verified/insufficient/rejected`状态都写入`verification_diagnostics.jsonl`。只有`verified`记录可以晋升到正式`attribution_claims.jsonl`；`insufficient`和`rejected`不进入正式Claim表。由于正式表中的状态恒为`verified`，正式Claim不重复保存`verification_status`字段。

### 10.2 Evidence Link

`evidence_links`必须同时支持Effect和Claim：

```text
target_type: effect / claim
target_id
support_field
evidence_id
span_id
char_start
char_end
span_text
support_label
```

`support_label`固定为：

```text
supports
contradicts
insufficient
```

每条链接只验证一个目标字段。字符偏移量绑定冻结后的`normalized_text`和`content_hash`。正式Effect或Claim必须至少具有一条`supports`链接；未晋升候选的`contradicts/insufficient`证据关系保留在验证诊断中。

### 10.3 Canonical Claim Group归并

下列字段用于Claim结构兼容检查，而不是简单exact composite key：

```text
(
  event_id,
  canonical_effect_id,
  relation_type,
  normalized_explanation,
  attribution_holder_category,
  polarity
)
```

每个归并结果统一使用字段`canonical_claim_group_id`标识，并根据`event_id + sorted(member_claim_ids)`确定性生成。

`semantic_label`与`merge_decision`严格分离。完全允许`semantic_label=equivalent_explanation`但因`attribution_holder_mismatch`得到`merge_decision=cannot_link`。Canonical Claim Group只聚合**语义等价且Attribution兼容**的Claim；`polarity`不同同样禁止归并。`other_or_unknown`与已知AttributionHolder之间默认进入裁决。

同一CanonicalEffect允许存在多个不同解释，包括EffectHolder的自身解释、政府或其他治理主体的外部解释、专家解释和媒体转述解释。即使解释内容等价，不同AttributionHolder也保留为不同Group，并在Group间保留`equivalent_explanation`关系。每条来源级Claim仍须保留Explanation、nullable `attribution_holder_surface`、AttributionHolder类别、ReportingSource、Evidence Span、`polarity`和`certainty`。

APCF遵循Redundancy reduction、Attribution preservation、Disagreement preservation和Provenance preservation四项原则，并采用false-merge-averse constrained aggregation。Pair层先独立产生`semantic_label`和`merge_decision=must_link/cannot_link/needs_adjudication`；Cluster自动merge必须满足所有必要cross-cluster pair均为`must_link`。任一`cannot_link`禁止merge，任一`needs_adjudication`或缺失判断均阻止自动merge并进入C队列。`additional/explicitly_contradicted/unresolved`不得通过传递性被压缩为一个解释。

LLM Pairwise与APCF必须读取同一批candidate pairs和同一个版本化semantic pair judgment资源，使用同一基础LLM、基础Prompt、temperature与解码设置。Claim candidate universe在Effect Fusion之前冻结，不得随各方法预测出的CanonicalEffect而改变；`canonical_effect_exact`只作为后续merge constraint。LLM Pairwise只作普通语义分组；APCF只能额外施加结构兼容、Attribution约束、cannot-link、complete-link一致性和来源谱系处理，不得通过更强语义Prompt取得额外优势。

### 10.4 跨来源关系

跨来源状态不存入单条Claim，而在Claim Pair或Claim Group层表达。

只有`primary_source_id`不同的Claim才进入跨来源Claim Pair判断。同一`primary_source_id`下的转载、重发或通稿副本先按来源谱系去重，不生成重复的`equivalent_explanation` Pair，也不计为独立印证。

Claim Pair关系为：

```text
equivalent_explanation
additional
explicitly_contradicted
unresolved
```

Claim Group汇总状态为：

```text
corroborated
complementary
contested
unresolved
single_source
```

不同解释不能仅因内容不同而自动判为矛盾。只有存在明确否定、互斥或不可同时成立的证据时，才能标为`explicitly_contradicted`。

`publication_time`或`claim_stage`差异本身不构成禁止`equivalent_explanation`的硬条件；只有当时间变化导致解释命题、适用阶段或极性发生实质变化时，才应标为`additional`或`unresolved`。本框架不新增`temporal_shift`关系。

Claim Pair和Claim Group用于表达解释之间的等价、补充、明确冲突或尚未解决的关系，从而回答“围绕同一Effect有哪些解释、分别由谁提出、出现在哪些来源、是否得到独立印证”。它们不负责选择或推断客观真实原因。

### 10.5 Attribution Gap分析视图

EffectHolder自己提出的解释可作为self-attribution，其他主体对该Effect提出的解释可作为external attribution。Event Dossier可以对二者进行并列展示，形成**stakeholder explanatory attribution structure**，并在案例分析中观察self-attribution与external attribution之间的差异，即attribution gap。

Attribution Gap只是在现有EffectHolder与AttributionHolder字段上计算的事件档案分析视图，不是新的关系标签、Gold字段、预测任务或方法模块。

## 11. 正式数据模型

Event Dossier的逻辑数据模型完整包含：

```text
Event
Stage
Document
Source
Effect
CanonicalEffect
AttributionClaim
CanonicalClaimGroup
ClaimPairRelation
EvidenceSpan
```

现有正式JSONL文件是该逻辑模型的序列化存储：

```text
sources.jsonl
documents.jsonl
viewpoint_effects.jsonl
attribution_claims.jsonl
evidence_links.jsonl
canonical_effects.jsonl
canonical_claim_groups.jsonl
claim_pair_relations.jsonl
event_dossiers.jsonl
```

过程性运行文件为：

```text
effect_candidates.jsonl
explanation_candidates.jsonl
relation_judgments.jsonl
verification_diagnostics.jsonl
semantic_pair_judgments.jsonl
fusion_pair_judgments.jsonl
fusion_cluster_diagnostics.jsonl
needs_adjudication.jsonl
```

`no_relation`和未通过验证的候选不进入正式Claim表。

`viewpoint_effects.jsonl`和`attribution_claims.jsonl`是M3冻结的来源级记录，不由Fusion回写Canonical ID。`canonical_effects.jsonl`与`canonical_claim_groups.jsonl`通过排序后的成员ID表达归属；正式路径只物化APCF结果，Exact、Embedding和LLM Pairwise写入各自隔离的实验目录，不得覆盖APCF正式文件。事件级组装再形成完整Event Opinion Graph。JSONL文件本身不是最终面向使用者的孤立输出。

## 12. Event Opinion Graph的作用与边界

**Event Opinion Graph是Event Dossier的正式信息组织模型，不是LLM抽取完成后的附加可视化。** 它负责组织经过验证的来源级结果、Canonical结构、来源和字段证据，不承担客观因果推理，也不预设图谱本身提高抽取F1。

主要节点为：

```text
Event
Stage
Document
Source
Effect
CanonicalEffect
AttributionClaim
CanonicalClaimGroup
EvidenceSpan
```

主要边包括：

```text
Event --contains--> CanonicalEffect
Effect --canonicalized_as--> CanonicalEffect
AttributionClaim --claim_about_effect--> Effect
AttributionClaim --belongs_to--> CanonicalClaimGroup
CanonicalClaimGroup --belongs_to--> CanonicalEffect
Effect --supported_by--> EvidenceSpan
AttributionClaim --supported_by--> EvidenceSpan
Effect / AttributionClaim --reported_in--> Document
Document --reported_by--> ReportingSource
Document --derived_from--> PrimarySource
CanonicalEffect --occurs_at--> Stage
AttributionClaim --asserted_at--> Stage
```

Claim Pair继续使用`equivalent_explanation`、`additional`、`explicitly_contradicted`和`unresolved`组织Canonical Claim Group内外的跨来源语义关系。

该图的实际作用是：跨Document连接同一CanonicalEffect；将多个来源级Claim组织到相应Effect；通过surface与category字段展示EffectHolder和AttributionHolder差异；保存Document与Source provenance；连接字段级Evidence Span；表示Claim间的等价、补充和明确冲突；支持Stage上的观点与解释演化查询；支持事件级审计和后续知识服务。

不得把来源提出的解释直接物化为无归属限定的：

```text
Explanation --causes--> Effect
```

## 13. 大模型的角色

**LLM负责语义理解，不负责直接生成最终Event Dossier。** 大模型用于：

- 高召回发现原子Effect候选；
- 判断Stakeholder Category；
- 提出受约束的隐式Explanation候选；
- 在固定关系集合内进行Relation Judgment；
- 识别AttributionHolder；
- 辅助字段级证据语义验证；
- 辅助Claim Pair语义关系判断。

确定性程序和规则负责：

- Document provenance与来源继承；
- `content_hash`与Evidence字符偏移；
- Schema及跨文件引用校验；
- 封闭标签映射；
- 结构兼容检查、共享语义pair judgment与保守APCF归并；
- 正式Event Opinion Graph物化。

大模型不得：

- 脱离证据自由生成原因；
- 将常识推断写成来源Claim；
- 将文本归属验证解释为现实因果证明；
- 自行扩展关系类型。

因此，最终Event Dossier由**LLM semantic atoms + field-level verification + constraint-aware APCF + provenance-aware graph organization**共同构成。本方法不能被简化描述为“LLM-based extraction”；其贡献也不是使用大模型替代因果推断，而是通过任务分解、类型约束、双主体建模、字段级验证和来源感知的事件级组织限制生成空间并保留审计链。

当前任务属于**high-recall exhaustive event profiling**：目标是尽可能完整发现一个Event中的重要Stakeholder Effect和Explanation。典型RAG属于query-driven selective retrieval，相关性筛选可能遗漏少数主体、弱信号观点或只在单一Document出现的信息。因此v1.5不引入LightRAG、EventRAG、GraphRAG或相应依赖，也不保留Pilot中的额外RAG方法模块；相关工作只能讨论其思想边界。

## 14. 实验设计

### 14.1 Pilot与Formal数据规模

数据集严格区分Pilot与Formal两部分：

```text
6 Pilot Events
+
60 Formal Events
=
66 total processed events
```

6个Pilot Event分别来自城市更新、教育、医疗、公共安全、城市交通和数字治理六个治理领域，每个领域1个。Pilot只用于M5试标、标注规范验证以及Prompt和流程调试；Pilot文档、Effect、Claim、Relation Candidate和Evidence Span不得进入正式Test数据或正式论文指标。

60个Formal Event是正式论文实验的唯一事件集合，按六领域均衡配置：

```text
城市更新：10
教育：10
医疗：10
公共安全：10
城市交通：10
数字治理：10
```

每个Formal Event保留约6至8篇有效Document，因此正式数据预计包含约360至480篇Document。不要求每个事件产生相同数量的Effect、Claim、Relation Candidate或Evidence Span。

正式规模设为60个事件的依据是：F1的直接评价实例是Effect、Claim、Relation Candidate和Evidence Span等，而不是Event本身；但同一事件内部实例共享文本、主体和事件语境，存在聚类相关性，因此Event是高层独立抽样与不确定性估计单位。每领域10个独立事件比每领域6个更适合观察跨事件稳定性，60个事件也在统计稳定性与双人Gold标注成本之间形成较均衡的折中。本研究不扩展到100个Formal Event，以避免约600至800篇Document带来的过高双人Gold标注成本。

Pilot与Formal Event均采用`criterion-based purposive sampling + maximum variation sampling`。所有Formal Event必须在正式Gold构建和正式实验前冻结；不得根据任何方法的模型表现选择、替换或排除事件。领域级结果只用于描述性分析，不把每领域10个事件表述为该领域总体的统计代表，也不因领域间F1差异作强因果或泛化结论。

阶段流程固定为：

```text
6 Pilot Events
-> M5试标
-> 冻结标注规范 / Prompt / Pipeline / Evaluation
-> 选择并冻结60个Formal Events
-> 构建正式Gold
-> Main comparison methods实验
-> 三项消融
-> pooled metrics + event-level robustness + event-cluster bootstrap
```

### 14.2 Main comparison methods与适用指标

1. **Long-context Event-level LLM：** 输入同一Event的全部Document，明确保留文档边界及`document_id`、`source_id`，一次直接生成完整Event Dossier；
2. **Long-context Event-level LLM + Evidence Requirement：** 输入同上，但要求每条Effect和Claim同时返回所属Document与Evidence Span；
3. **Direct Explanation–Effect Pair Classification：** 仅在所有方法共享的固定Gold Candidate Set上评价Relation Decision；
4. **原EpiSOA：** 通过所有方法共享的评测适配层输出公共评价Schema；其中Stakeholder、Stance和Emotion映射到统一封闭标签，Rationale映射为Explanation，原方法不能产生的双主体或字段级验证字段按预注册的缺失值规则保留，而不由适配层补推断；
5. **EpiSOA-EA：** 完整执行Document-level extraction、field-level verification、cross-document canonicalization和provenance-aware Event Dossier construction。

上述五项统称Main comparison methods，不称为“五个端到端方法”。完整Event-Dossier architecture comparison只包含Long-context、Long-context + Evidence和EpiSOA-EA；Direct Pair只评价固定候选集上的Relation Decision，Original EpiSOA作为historical baseline只报告其能够忠实产生的Effect、limited Relation/Claim/Evidence指标，不为不支持的输出伪造Dossier分数。

所有方法必须使用完全相同的Formal Events、Document集合、冻结`normalized_text`、文档/来源ID、Gold、封闭标签、规范化器和评价代码。Long-context输入必须包含该Event的全部有效Document及清晰边界，不得静默截断。Gold和各方法对`Stakeholder Category`、`Stance`和`Emotion`使用同一封闭标签空间、公共评价Schema和映射规则；不得为EpiSOA-EA单独提供后处理规范化器。

60个Formal Event及其Document冻结后、第一次模型推理之前，使用候选模型官方Tokenizer计算包含Prompt和reserved output budget的最大Event输入，选择能够容纳该输入的模型并冻结provider/model/version。Long-context与EpiSOA-EA使用同一基础LLM。推理开始后不得依据Formal结果换模型；`capacity_failure`单独报告且不计为普通FN，并阻断不完整的60-Event主表。若确需换模型，必须先废弃未完成运行、更新冻结Manifest并完整重跑全部LLM方法。正式结果同时报告调用数、输入/输出token、运行时间和最大上下文长度。

### 14.3 诊断性实验

- Gold Effect Candidates；
- Gold Explanation/Evidence Candidates。

两项诊断实验用于区分Effect发现、Explanation候选构建和关系判断造成的误差。

Fusion独立比较Exact、Embedding、LLM Pairwise和APCF。四者共享Gold、宽松blocking候选集、规范化器、数据划分与评价代码；其中LLM Pairwise和APCF额外共享完全相同的semantic pair judgment资源。Fusion评价分四层：Gold source Effects上的Effect Fusion；Gold source Claims + Gold Canonical Effects上的Claim Fusion Oracle；Predicted Canonical Effects上的Full Fusion；以及Raw Documents到Event Dossier的End-to-End。Claim Fusion Oracle与Full Fusion必须分表报告。

Pilot对同Event、仅应用不可违反类型约束的pair universe做近似穷举Blocking审计，分别计算Effect和Claim Candidate Blocking Recall。阈值预注册为0.98；达标后冻结blocker，Formal不得依据融合结果继续调参或换规则。未裁决pair不进入Canonical P/R/F1分母，但必须报告数量与覆盖率。

### 14.4 核心消融

只保留三个核心消融：

```text
w/o Type Constraint
w/o Dual Attribution
w/o Field-Level Verification
```

不再为论文主线增加其他方法模块。

APCF另设三项机制诊断消融：`w/o Attribution Constraint`、`w/o Cluster Consistency`和`w/o Provenance-aware Source Deduplication`。前两项隔离归属约束与complete-link机制；最后一项只评价Source Independence Overcount，不解释为Canonical准确率消融。所有消融共享同一semantic judgment资源、候选集、模型、Prompt、解码和阈值。

### 14.5 预注册的结果解释与架构证伪

本研究不把贡献建立在“EpiSOA-EA必须获得最高Extraction F1”之上。正式实验前冻结三类可接受解释：

- **情况A：** EpiSOA-EA同时改善抽取准确率与证据、归属和审计可信性；
- **情况B：** Long-context LLM的F1相当或略高，但EpiSOA-EA在Holder mismatch、Unsupported Claim、Evidence localization、Source traceability、Audit time和Cross-document contamination上更好。此时结论是结构化Document-to-Event pipeline以有限准确率代价换取更强可追溯性和审计能力；
- **情况C：** Long-context LLM在准确率、证据和归属指标上均明显优于EpiSOA-EA。该结果是架构证伪信号，不得事后强行包装；若在M5 Pilot诊断中出现，应在60个Formal Event冻结和正式实验前简化架构并重新冻结设计。

## 15. 评价指标

### 15.1 抽取与关系

```text
Stakeholder Category F1
Stance Macro-F1
Emotion Macro-F1
Action F1
Viewpoint Effect F1
Relation Decision Macro-F1
Attribution Claim F1
```

`Relation Decision Macro-F1`必须在所有方法共享的固定金标准候选集上计算，标签固定为：

```text
stance_rationale
emotion_trigger
action_motivation
no_relation
```

完整文本到正式Claim的端到端结果另用`Attribution Claim F1`评价。

`Attribution Claim F1`的结构匹配基于规范化后的`Stakeholder Category`、`Effect Type`、`Effect Value`、`Relation Type`和`AttributionHolder Category`，并结合Explanation语义匹配或Gold预定义的规范化结果。不得仅因主体原文称谓不同而将整条Claim判为不匹配。Action和Explanation保留开放文本及字段级证据评价。

Explanation不要求`normalized_explanation`字符串完全一致：Gold与预测Span在同一文档中的中文字符级F1达到0.5，或二者命中所有方法共享的冻结、版本化语义等价规则，即可匹配；评价输出必须记录`span_overlap`或`semantic_rule`匹配路径。`Holder Category Mismatch Rate`在其余Claim字段及Explanation已对齐的样本上，统计预测的EffectHolder/AttributionHolder“同类或异类”关系与Gold不一致的比例，避免与AttributionHolder Category Accuracy重复。

### 15.2 主体、证据与审计

```text
AttributionHolder Category Accuracy
Holder Category Mismatch Rate
Chinese Character-Level Evidence Span F1
Unsupported Claim Rate
False Acceptance Rate
False Rejection Rate
Median Human Audit Time
Audit Decision Accuracy
Evidence Localization Success Rate
Source Traceability Rate
Cross-document Attribution Contamination Rate
```

False Acceptance与False Rejection均在同一固定验证候选集上计算：前者统计Gold不应晋升却被判为`verified`的比例，后者统计Gold应晋升却被判为`insufficient/rejected`的比例。

F1用于证明基本任务有效性。论文的核心价值主张是：在可接受的准确率代价下，增强观点成因结果的证据关联、归属主体区分、来源追溯和字段级审计能力。

`Cross-document Attribution Contamination Rate`统计被评估预测Claim中，将不同Document的EffectHolder、Explanation、AttributionHolder或Evidence错误拼接为任何原文都不存在的归属关系的比例；分母是纳入该项人工或规则复核的全部预测Claim，分子是确认发生上述跨文档拼接的Claim，数值越低越好。判定必须使用所有方法共享的冻结Gold和裁决规则，重点比较两个Long-context Event-level LLM与EpiSOA-EA。

例如，D1记载“居民说反对是因为补偿低”，D2记载“政府认为居民是因为政策理解不足”。若系统输出“居民表示自己因为政策理解不足而反对”，即把D2的外部解释错误改写成居民自我解释，计为一次跨文档归属污染。仅仅综合多个文档但仍准确保留每个Claim的提出者、来源和证据，不计为污染。

### 15.3 三层评价报告与事件聚类不确定性

正式评价只使用冻结的60个Formal Event，并采用三层结果报告。

第一层是实例级总体指标，也是论文主要结果。对60个Formal Event中的相应评价实例统一汇总计算：

```text
Stakeholder Category F1
Stance Macro-F1
Emotion Macro-F1
Relation Decision Macro-F1
Attribution Claim F1
Evidence Span F1
Cross-document Attribution Contamination Rate
以及本节已冻结的其他指标
```

总体指标不得包含Pilot实例。跨文档或跨事件记录不得互相匹配；各指标先在原有文档/事件边界内确定TP、FP、FN或其他统计量，再对全部Formal Event汇总。

第二层是事件级稳健性。分别计算每个Event的主要指标，并报告event-level mean、median及离散程度，用于检查pooled结果是否由少数大事件或容易事件主导。某Event没有某项指标所需的Gold评价实例时，该事件在该项指标上记为`NA`而不是0，并同时报告该指标的有效事件数。

第三层是事件聚类Bootstrap置信区间。以Event为重采样单位，每次从60个Formal Event中有放回抽取60个Event，将每个抽中Event的全部评价实例按其抽中次数整体纳入，并重新计算pooled指标。Bootstrap重复次数在正式实验前从1000至5000次范围内预注册；主要指标报告95%置信区间。不得把全部Claim或其他实例视为彼此独立后直接重采样。

比较EpiSOA-EA与任一基线时采用配对Event Bootstrap。所有方法必须使用完全相同的Formal Event、Document和Gold；每次Bootstrap对所有方法使用同一批有放回抽取的Event，并基于该次重采样计算`EpiSOA-EA - baseline`的指标差及其95%置信区间。

每领域10个Formal Event可以报告领域级描述性性能和离散情况，但不得据此声称对整个领域具有统计代表性，也不得仅根据领域间F1差异推断领域属性造成性能差异。

### 15.4 Event Dossier Case Study

正式论文从60个Formal Event中选择1–2个事件开展Event Dossier Case Study，用于展示单一多来源事件的实际信息组织价值。案例选择依据在查看Main comparison methods结果前预注册，优先采用文档来源多样、阶段覆盖较完整、存在多个Stakeholder和多种Explanation Attribution的结构丰富性标准，不得根据EpiSOA-EA表现较好而选择案例。

案例至少分析四类结构：

1. **Stakeholder–Effect Structure：** 谁针对什么Target持有什么Stance、Emotion或Action；
2. **Attribution Structure：** 谁持有Effect、谁解释该Effect，重点并列展示self-attribution与external attribution；
3. **Source–Claim Structure：** 比较official、media、affected_public、expert等来源或主体分别突出哪些解释，以及解释之间的印证、补充或明确冲突；
4. **Stage Evolution：** 沿`trigger`、`diffusion`、`conflict`、`response`、`resolution`和`follow_up`观察观点、行动和解释结构如何变化。

Case Study只描述可追溯的信息结构和观点演化，不推断客观因果，不替代60个Formal Event上的pooled metrics、event-level robustness或event-cluster bootstrap。

### 15.5 试标一致性门槛

正式试标前固定以下最低门槛：

- Stakeholder Category和AttributionHolder Category：类别一致率不低于0.80；
- Effect类型和Relation Decision：Cohen's kappa（两名标注员）或Fleiss' kappa（三名及以上标注员）不低于0.80；
- implicit关系的Relation Decision：一致性不低于0.70；
- Evidence Span：中文字符级F1不低于0.75。

implicit关系的一致性同样使用Cohen's kappa或Fleiss' kappa；Evidence Span使用标注员两两字符级F1。任一核心门槛未达到时，先修订标注边界并重新试标，不扩大正式数据规模，也不得事后降低门槛以迁就结果。

M5工程正确性门禁必须100%满足：无hard-constraint violation、无Gold循环依赖、Span全部可回读、Dossier provenance无断链、确定性转载测试Overcount为0，并且Candidate Blocking Recall达到0.98。False Merge、Pairwise F1和Conflict Preservation仅作Pilot描述性比较；相对最佳方法F1下降不超过0.05只是工程决策阈值。Conflict Preservation仅在Pilot具有足够的Gold contradiction pair时参与门禁，否则报告原始数量并记为`NA`，不得因无样本自动记为1.0。

## 16. 核心创新点

1. **Evidence-grounded Explanatory Attribution：** 从Document中结构化“谁针对什么Target持有或实施何种Effect、该Effect由谁用什么Explanation解释、在哪里被报道、由哪些字段级Evidence支持”，统一覆盖立场理由、情绪触发因素和行动动机而不扩张为一般因果推断；
2. **Attribution-Preserving Canonical Fusion：** 通过共享语义对齐、Attribution约束、complete-link一致性和`primary_source_id`来源谱系处理，把分散来源组织成事件级结构，同时保留主体归属、分歧和证据，不强行生成单一“真相”；
3. **Event Opinion Graph / Event Dossier：** 提出面向单个多来源公共事件的可查询、可验证、可追溯信息组织结构，统一连接Stakeholder、Effect、Explanation、Attribution、Stage、Source、Evidence和跨来源关系。

“使用LLM”或“使用知识图谱”本身均不作为创新点。

## 17. 论文核心叙事

重点公共事件的信息分散在新闻、官方材料、公共互动和其他异质来源中。一般事件监测或LLM摘要能够概括发生了什么或整体情绪，却难以稳定回答：谁针对什么对象持有什么观点或采取什么行动；主体自身、政府、专家或其他主体分别如何解释；不同来源是否相互印证、补充或明确冲突；每项结论来自哪里、原文证据在哪里。

EpiSOA-EA以文档为抽取单位、以单个事件为实际应用与分析单位，通过Document-level semantic extraction、field-level evidence verification、cross-document canonicalization和provenance-aware integration构建Event Opinion Graph，最终形成可查询、可追溯、可审计的Event Dossier。它不让大模型自由推测真实原因，也不把异质解释压缩成“公众总体立场”或唯一真相；surface字段服务人类理解与来源回读，category字段服务规范化、归并和评价。

Event Dossier面向事件研判、专题分析、证据核查和后续知识服务。平台化、实时采集和自动监控只作为未来应用场景，不是当前论文主任务。

## 18. 实施纪律

- 本文档是论文目标方法的权威定义；
- [`annotation_guidelines.md`](annotation_guidelines.md)是人工标注和金标准构建的权威定义；
- 当前`soe_v3`代码是遗留实现；并行`src/episoa/ea/`已实现v1.5 Schema、阶段隔离、APCF、Dossier、Fusion Gold/评价和Long-context离线门禁；
- 代码与合成测试通过只表示M5之前的工程准备完成，不表示六事件Pilot、真实API、正式Gold、60事件实验或论文结果已经完成；
- 实施期间只允许为本框架已有模块补充代码、Schema、测试和必要配置；
- 不新增LightRAG、EventRAG或GraphRAG主流程依赖；
- 如果试标暴露一致性问题，优先修订标签边界和案例，不自行增加关系类型或方法模块。
