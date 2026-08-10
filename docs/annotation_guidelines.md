# EpiSOA-EA 标注规范（冻结版）

版本：1.5
状态：用于M5试标。v1.5 Schema、APCF、Dossier和离线Gold/评价工具已实现；六事件人工试标、真实API、正式Gold和60事件实验尚未执行。

权威方法定义：[`method_framework.md`](method_framework.md)

## 1. 标注目标

本规范用于从多来源公共事件文本中标注：

1. 哪个主体在何时持有什么立场、产生什么情绪或实施什么行动；
2. 文本用什么解释说明该立场、情绪或行动；
3. 谁提出该解释，哪个来源报道该解释；
4. 哪些原文片段支持Effect和Claim的具体字段；
5. 不同来源的Claim是等价、补充、明确矛盾还是暂时无法判断。

本任务标注的是**文本表达的观点成因归属**，不判断解释是否为现实世界中的真实原因，不进行反事实因果推断、责任裁决或一般事件因果图构建。

实际应用对象是一个具体的多来源公共事件。标注结果最终用于组装字段证据可验证、来源可追溯、跨来源观点可比较的Event Dossier / Event Opinion Graph。60个Formal Event只是检验该档案构建方法跨治理情境稳定性的Benchmark corpus，不是60个各自只产生一条标签的浅层研究对象。

## 2. 标注对象与顺序

严格按照以下顺序标注：

```text
Document/Source
  -> Stakeholder Category
  -> Viewpoint Effect
  -> Explanation Candidate
  -> Attribution Claim
  -> Evidence Link
  -> Canonical Effect
  -> Canonical Claim Group
  -> Claim Pair Relation
  -> Event Opinion Graph / Event Dossier
```

不得先根据常识写出原因，再回到文本中寻找证据。所有正式Effect和Claim都必须能够定位到规范化正文中的原文片段。

**抽取单位是文档，分析单位是事件。** 标注员必须逐篇文档独立标注来源级Effect、Attribution Claim和字段级Evidence Span，不得先拼接同一事件的多篇文档再生成事件级结果。每篇Document允许独立产生0–N条Effect、0–N条Attribution Claim和0–N条Evidence Link：没有对应表达时为0条，出现多个主体、stance、emotion、action或explanation时应拆为多条，不得假定“一篇Document对应一个输出”。每条Effect和Claim都必须保留`document_id`、`reporting_source_id`及来源继承信息；完成单篇文档标注后，才可在相同`event_id`内进行主体类别归一、Effect归并/去重、Canonical Claim归并、Claim Pair判断及跨来源支持、补充和矛盾分析。事件级结果必须能够回溯到具体文档和具体Evidence Span。

## 3. 文档与来源谱系

### 3.1 文档记录

每篇文档至少记录：

```text
document_id
event_id
reporting_source_id
parent_document_id
primary_source_id
publication_time
content_hash
derivation_type
normalized_text
```

其中`reporting_source_id`必须引用`sources.jsonl`，不能悬空，也不能以EffectHolder或AttributionHolder类别替代。

字符偏移量统一以带有`content_hash`的`normalized_text`为准。正文冻结后不得在不更新哈希和偏移量的情况下修改文本。

### 3.2 derivation_type

`derivation_type`描述文档内容的继承方式：

| 取值 | 判定规则 |
|---|---|
| `original` | 当前来源是可识别的原始发布者或原始采访者 |
| `independent_report` | 独立采写且形成新的primary-source lineage |
| `official_republication` | 完整或近完整转载官方材料 |
| `syndicated_copy` | 通稿、供稿或媒体间近重复转载 |
| `quoted_from_other_source` | 文档具有自身内容，但关键Claim明确引自其他来源 |
| `synthesized_from_multiple_sources` | 文档综合多个可识别来源形成报道 |
| `unknown` | 现有信息不足以判断 |

### 3.3 来源谱系统计

v1.5不标注Claim级`source_independence`，也不增加`partially_independent`。标注员只确认`primary_source_id`和`derivation_type`。程序据此派生`document_multiplicity`、`primary_source_multiplicity`、`dependent_reproduction_count`和`unknown_lineage_count`。`unknown`谱系不得自动视为独立来源，转载网页数量不得直接当作独立支持数量。

### 3.4 ReportingSource规范表

ReportingSource统一保存在`sources.jsonl`，至少包含：

```text
source_id
source_name
source_type
```

ReportingSource表示具体发布渠道，AttributionHolder表示解释提出者，两者不得因名称相同而合并角色。

## 4. 统一主体类别

EffectHolder和AttributionHolder使用同一抽象类别空间，不做具体人物级实体归并。正式类别固定为：

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

| 类别 | 判定规则 |
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

EffectHolder必须标注非空`holder_surface`、`holder_role`和`stakeholder_category`，其中`holder_surface`必须由原文Evidence支持。AttributionHolder必须标注`attribution_holder_role`和`attribution_holder_category`，但`attribution_holder_surface`允许为`null`：仅在原文明确出现解释提出者称谓时填写，非null时必须有Evidence；隐式归因或`other_or_unknown`无明确称谓时不得编造surface。**surface用于人类理解和来源追溯，category用于规范化、兼容检查和评价。**

例如：

```text
holder_surface = "3号楼业主王先生"
holder_role = "业主"
stakeholder_category = "affected_public"

attribution_holder_surface = "街道办相关负责人"
attribution_holder_role = "街道办"
attribution_holder_category = "government"
```

具体人名或组织名称不要求跨文档消歧；记录surface不得被解释为新增人物级实体识别或跨文档实体归并任务。

标注规则：

- “有关部门”标为`government`，“有专家认为”标为`expert`；“知情人士”等证据不足以可靠分类的主体标为`other_or_unknown`，不创建人物级规范实体；
- 不得仅因报道由某媒体发布，就把该媒体自动标为AttributionHolder；
- 转述结构中，原始说话者是AttributionHolder，当前发布机构是ReportingSource；
- 无法从文本确定解释提出者类别时，使用`attribution_holder_category=other_or_unknown`，不得默认等于EffectHolder；
- 当直接引语、间接引语、第一人称陈述或明确的意图表达表明解释由EffectHolder本人提出，且不存在第三方归因标记时，允许EffectHolder Category与AttributionHolder Category相同。这属于有证据的主体自身归因，不是默认推断；裸叙述“居民因X拒绝”本身不足以证明居民亲自提出了该解释；
- “业主王先生”标为`holder_surface=业主王先生`、`holder_role=业主`、`stakeholder_category=affected_public`，不要求跨文档判断其是否与另一篇文档中的“王某”是同一人物。

## 5. Viewpoint Effect标注

### 5.1 原子标注单位

一个Effect只能包含一个主体、一个目标、一种Effect类型和一个Effect值：

```text
<EffectHolder, EffectType, EffectValue, Target, EffectStage>
```

“居民反对方案并拒绝签约”必须拆为两个Effect：

```text
居民—stance—oppose—方案
居民—action—拒绝签约—签约安排
```

### 5.2 Effect类型

| 类型 | 定义 | 典型表现 |
|---|---|---|
| `stance` | 对对象的支持、反对、接受、质疑或评价立场 | 支持、反对、认可、质疑 |
| `emotion` | 主体明确表现或被明确描述的情绪状态 | 担忧、愤怒、满意、失望 |
| `action` | 主体已经实施、正在实施或明确决定实施的行为 | 签约、投诉、协商、拒绝搬迁 |

仅有可能性、建议或计划时，不得标成已经发生的行动；应依据文本时态和情态确定是否形成Action。

### 5.3 Stance封闭标签

Stance的`effect_value`只能为：

| 标签 | 定义 |
|---|---|
| `support` | 明确支持、赞同、接受或认可目标对象 |
| `oppose` | 明确反对、拒绝或不接受目标对象 |
| `question` | 质疑目标对象、真实性、合理性、程序或解释，但尚不能等同于明确反对 |
| `neutral` | 文本确实表达立场，但明确表现为中立或无明显支持、反对倾向 |
| `uncertain` | 文本确实存在立场表达，但现有证据不足以可靠判断其类别 |

语义等价而措辞不同的表达必须映射到同一标签。例如“不接受现有方案”“反对该方案”“不同意现行安排”均标为`oppose`。

文本没有表达对应立场时，不创建Stance Effect。`uncertain`只表示“存在立场表达，但类别无法可靠判断”，不能用于表示“没有立场字段”。

### 5.4 Emotion封闭标签

Emotion的`effect_value`只能为：

| 标签 | 定义 |
|---|---|
| `positive` | 满意、认可、欣慰、积极等总体正向情绪 |
| `negative` | 不满、愤怒、担忧、失望、焦虑等总体负向情绪 |
| `neutral` | 文本确实表达某种情绪状态，但该状态无明显正负极性 |
| `uncertain` | 文本确实存在情绪表达，但无法根据证据可靠判断其极性 |

“不满”“担忧”“愤怒”“失望”等具体措辞均标为`negative`，原词由`effect_surface`及Evidence Span保留。不增加anger、fear、sadness等细粒度情绪标签。

文本没有表达情绪时，不创建Emotion Effect。纯事实陈述不创建Emotion Effect，不能标为`neutral`。`uncertain`只表示“存在情绪表达，但类别无法可靠判断”，不能用于表示“没有情绪字段”。

Action继续使用规范化短语，不强制建立跨事件统一Action类别体系。Explanation继续使用开放文本。

### 5.5 effect_stage

`effect_stage`表示立场、情绪或行动发生的事件阶段，而不是文档发布时间。

`effect_stage`和后文的`claim_stage`共用以下受控标签：

| 标签 | 含义 |
|---|---|
| `trigger` | 事件触发、问题出现或关键决定首次发生 |
| `diffusion` | 信息传播、关注扩散或议题形成 |
| `conflict` | 利益分歧、公开争议或对抗集中出现 |
| `response` | 相关主体回应、协商、处置或调整 |
| `resolution` | 形成阶段性解决方案、决定或结果 |
| `follow_up` | 后续执行、反馈、复盘或持续影响 |
| `unknown` | 证据不足，不能可靠归入以上阶段 |

判定优先级：

1. 原文明确说明Effect发生时间；
2. 可由同一事件中有证据支持的时间锚点定位；
3. 无法可靠定位时标记`unknown`。

不得仅凭文档发布日期推断`effect_stage`。

### 5.6 Effect输出

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

`effect_surface`保存原文表述，`effect_value`保存规范化值。二者分别用于检查原文抽取错误和规范化错误，不得只保留其中之一。

Emotion示例：

```json
{
  "effect_id": "EF002",
  "event_id": "E001",
  "document_id": "D001",
  "reporting_source_id": "SRC001",
  "primary_source_id": "SRC001",
  "derivation_type": "original",
  "holder_surface": "3号楼业主王先生",
  "stakeholder_category": "affected_public",
  "holder_role": "业主",
  "effect_type": "emotion",
  "effect_surface": "对补偿安置方案感到不满",
  "effect_value": "negative",
  "target": "补偿安置方案",
  "effect_stage": "conflict"
}
```

每条Effect的字段必须通过一条或多条Evidence Link定位到当前`document_id`的冻结正文。

### 5.7 canonical_effect_id生成规则

`effect_id`标识来源级Effect；CanonicalEffect是类别级观点命题，不是actor coreference。以下字段是compatibility dimensions，而不是exact composite key：

```text
event_id、stakeholder_category、effect_type：hard exact
Stance/Emotion effect_value：closed-label hard exact
Action effect_value、Target：semantic compatibility
effect_stage：observation attribute
```

Target和开放Action允许通过冻结的语义pair judgment确认等价，不要求规范化字符串完全相同。Stage不参与身份；来源级Effect保留Stage，CanonicalEffect派生`observed_stages`，只有明确时间语义冲突才阻止归并。`holder_surface`不参与跨文档人物共指，但必须保留在成员Effect中。`canonical_effect_id`由程序基于`event_id + sorted(member_effect_ids)`生成；歧义只进入C裁决，不增加人工Canonical标注层。

Canonical归并不得删除来源级Effect。每条Effect的`holder_surface`、`document_id`、ReportingSource和Evidence Span必须继续保留并链接到CanonicalEffect。同一`stakeholder_category`可以同时具有`support`、`oppose`、`question`等多个CanonicalEffect，不得标注或派生“公众总体立场”这类强制汇总标签。

## 6. Explanation Candidate标注

围绕每个Effect标注可能解释该Effect的候选片段。候选来源包括：

```text
explicit_cue
argument_structure
cross_sentence
temporal_compatible
llm_proposed
```

候选至少应满足：

```text
same_event
temporal_compatible
contextually_connected
type_compatible
participant_consistent
```

时间先后只能用于排除不可能的方向，不能单独证明解释关系。背景事实与Effect同时出现，也不能仅凭共现标为成因解释。

试标阶段不设置固定Top-K硬截断，以免在高召回候选阶段漏掉少数类解释。候选过多时分批判断；若正式实验确需上限，必须在查看测试结果前预注册K，并同时报告候选召回率。

## 7. Attribution Claim标注

### 7.1 正式关系类型

| Effect类型 | 唯一允许的关系 |
|---|---|
| `stance` | `stance_rationale` |
| `emotion` | `emotion_trigger` |
| `action` | `action_motivation` |

候选判断标签为：

```text
supported
no_relation
```

`no_relation`只保存在候选判断文件中。正式Claim表只接收通过关系判断的Claim，因此不保存恒定的`relation_decision=supported`字段。

### 7.2 双主体归属

- `stakeholder_category`：持有立场、产生情绪或实施行动的EffectHolder类别；
- `holder_surface`：原文中的具体EffectHolder称谓；
- `attribution_holder_category`：提出相关解释的AttributionHolder类别；
- `attribution_holder_surface`：原文中的具体AttributionHolder称谓；
- `reporting_source_id`：记录或发布该解释的来源。

三者必须分别判断，不得自动合并。

例句：“官方认为，居民拒绝签约是因为对政策理解不足。”

```text
EffectHolder Category：affected_public
EffectHolder Surface：居民
EffectHolder Role：居民
Effect：拒绝签约
AttributionHolder Category：government
AttributionHolder Surface：官方
AttributionHolder Role：官方/相关部门
Explanation：居民对政策理解不足
ReportingSource：当前文档发布机构
```

### 7.3 Claim属性

```text
explicitness: explicit / implicit
certainty: certain / uncertain
polarity: affirmed / denied
```

- `explicit`：原文使用明确的理由、动机或触发表达；
- `implicit`：没有显式提示词，但语篇结构明确建立解释关系；
- `certain`：来源将解释作为确定陈述提出；
- `uncertain`：来源使用“可能、或因、疑似”等不确定表达；
- `affirmed`：来源肯定该解释；
- `denied`：来源明确否定该解释。

否定某个解释仍可形成Claim，但必须标为`denied`，不能与相同内容的`affirmed` Claim归并。

### 7.4 claim_stage

`claim_stage`表示成因解释被提出或被报道时所处的事件阶段，与`effect_stage`分开标注。

判定规则：

1. 能确定解释首次提出的时间时，以该时间对应阶段为准；
2. 只能确定当前报道时间时，以报道时间对应阶段为准；
3. 原文与可靠元数据均不足时标记`unknown`；
4. 不得因为Claim解释某个早期Effect，就自动令`claim_stage=effect_stage`。

### 7.5 Claim输出

```json
{
  "claim_id": "CL001",
  "effect_id": "EF001",
  "explanation_surface": "补偿标准低于他们的预期",
  "normalized_explanation": "补偿标准低于预期",
  "relation_type": "stance_rationale",
  "attribution_holder_surface": "业主代表李女士",
  "attribution_holder_category": "affected_public",
  "attribution_holder_role": "业主代表",
  "document_id": "D001",
  "reporting_source_id": "SRC001",
  "primary_source_id": "SRC001",
  "derivation_type": "original",
  "claim_stage": "conflict",
  "explicitness": "explicit",
  "certainty": "certain",
  "polarity": "affirmed"
}
```

`attribution_holder_surface`仅在原文明确出现具体解释提出者称谓时填写，否则为`null`；非null时必须有Evidence。`attribution_holder_category`使用第4节的九类受控标签，`attribution_holder_role`保留原始角色。M3来源级Claim不填写Canonical ID，Fusion通过成员表表达归属。Claim通过`effect_id`引用EffectHolder，并保留当前文档、ReportingSource和来源谱系信息。

`explanation_surface`保存原文表述，`normalized_explanation`保存规范化后的解释命题。两者分别用于检查原文抽取错误和规范化错误。

## 8. Evidence Link标注

`evidence_links`同时支持Effect和Claim：

```json
{
  "evidence_link_id": "EL001",
  "target_type": "claim",
  "target_id": "CL001",
  "evidence_id": "EV001",
  "span_id": "SP001",
  "char_start": 128,
  "char_end": 153,
  "span_text": "因补偿标准低于预期，多名居民拒绝签约",
  "support_field": "relation",
  "support_label": "supports"
}
```

`support_label`固定为：

```text
supports
contradicts
insufficient
```

- `supports`：Span足以支持目标字段；
- `contradicts`：Span明确反驳目标字段或其方向；
- `insufficient`：Span提及相关内容，但不足以支持目标字段。

不增加`mentions_only`等其他标签。正式Effect或Claim必须至少具有一条`supports`链接；未晋升候选的`contradicts/insufficient`链接保留在验证诊断中。

### 8.1 Effect支持字段

```text
stakeholder_category
holder_surface
target
effect_type
effect_value
effect_stage
```

### 8.2 Claim支持字段

```text
explanation_surface
relation_type
attribution_holder_category
attribution_holder_surface（仅非null时必需）
explicitness
certainty
polarity
```

### 8.3 证据跨度规则

- 选择能够独立支持目标字段的最短充分片段；
- 同一字段需要跨句支持时允许链接多个Span，不得人为拼接非连续文本；
- 代词指代需要上下文才能确定时，同时链接代词所在Span和先行词所在Span；
- 每条Evidence Link只对应一个`support_field`；
- 不得用标题、摘要或模型解释替代正文证据，除非它们本身属于冻结后的可标注文本。

## 9. 字段级验证

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

最终状态：

| 状态 | 定义 |
|---|---|
| `verified` | 原文足以支持目标字段以及“某主体提出了该解释”这一文本归属关系 |
| `insufficient` | 部分必要字段或关系缺少充分原文支持 |
| `rejected` | 存在主体错误、方向颠倒、关系不存在或明显无依据推断 |

**重要语义边界：**`verified`仅表示原文确实支持“某主体提出了该解释”，不表示该解释是现实世界中的真实原因。

所有验证尝试均写入`verification_diagnostics.jsonl`并保留`verified/insufficient/rejected`状态。只有`verified`记录进入正式`attribution_claims.jsonl`；`insufficient/rejected`不进入正式Claim表。由于正式表中的状态恒为`verified`，正式Claim不保存恒定的`verification_status`字段。

## 10. Canonical Claim Group归并

下列字段用于Claim结构兼容检查，不构成简单exact composite key：

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

每个归并结果统一使用`canonical_claim_group_id`标识，并按`event_id + sorted(member_claim_ids)`确定性生成。

归并规则：

- Claim必须引用同一CanonicalEffect；
- `document_id`和`reporting_source_id`不进入归并键；
- `polarity`必须进入归并键；
- `semantic_label`与`merge_decision`分别标注；解释可语义等价但因AttributionHolder不同而`cannot_link`；
- 只有核心命题语义等价、Attribution兼容且极性一致时才可归并；
- 解释粒度明显不同但可以并存时，应保留为不同Claim，再判断为`additional`。

同一CanonicalEffect可以同时连接居民自身解释、政府对居民的解释、专家解释或媒体转述解释。不得将这些Explanation强行融合成唯一原因。解释等价但AttributionHolder不同的Claim保留在不同Group，Group间标注`equivalent_explanation`。归并后仍分别保留每条来源级Claim的Explanation、nullable `attribution_holder_surface`、AttributionHolder类别、Source、Evidence、`polarity`和`certainty`。

自动Cluster merge必须满足所有必要cross-cluster pair均为`must_link`；任一`cannot_link`禁止merge，任一`needs_adjudication`或缺失判断阻止自动merge并进入C队列。不得仅因“没有发现cannot-link”而合并，也不得通过A–B、B–C传递性跳过A–C判断。

## 11. 跨来源Claim关系

### 11.1 Claim Pair层

只有`primary_source_id`不同的来源级Claim才进入跨来源Claim Pair标注。同一`primary_source_id`下的转载、重发或通稿副本先去重，不生成重复Pair，也不计为独立印证。

符合上述条件的两个Claim之间标注：

```text
equivalent_explanation
additional
explicitly_contradicted
unresolved
```

- `equivalent_explanation`：核心解释命题语义等价；它不自动意味着允许归并；
- `additional`：解释不同但可以同时成立，形成信息补充；
- `explicitly_contradicted`：存在明确否定、互斥或不可同时成立的表达；
- `unresolved`：证据不足以确定关系。

不同解释不能仅因内容不同而标为矛盾。

`publication_time`或`claim_stage`相距较远本身不禁止标记`equivalent_explanation`。只有时间变化导致解释命题、适用阶段或极性发生实质变化时，才标为`additional`或`unresolved`；不新增`temporal_shift`标签。

### 11.2 Claim Group层

Group状态由Pair关系和独立来源情况派生：

```text
corroborated
complementary
contested
unresolved
single_source
```

跨来源状态不写入单条`attribution_claims`记录。

Claim Pair和Claim Group只组织来源提出的解释是否等价、补充、明确冲突或尚不能判断，不裁决哪一个是客观真实原因。基于现有EffectHolder与AttributionHolder字段，可以在Event Dossier中并列展示self-attribution和external attribution并观察attribution gap；它只是分析视图，不新增关系标签、Gold字段或预测任务。

## 12. 正例、负例与边界案例

### 12.1 显式正例

“居民表示，由于补偿标准低于预期，他们拒绝签约。”

```text
Effect：居民—action—拒绝签约
Explanation：补偿标准低于预期
Relation：action_motivation
EffectHolder Category：affected_public
AttributionHolder Category：affected_public（由“居民表示”明确支持）
Explicitness：explicit
Polarity：affirmed
```

### 12.2 共现负例

“补偿方案于周一公布，多名居民周二参加座谈会。”

两个事实存在时间邻接，但没有建立动机关系，应标为`no_relation`。

### 12.3 报道者不等于解释提出者

“本报记者了解到，专家认为居民的担忧源于信息不透明。”

```text
EffectHolder Category：affected_public
AttributionHolder Category：expert
ReportingSource：媒体
```

### 12.4 否定解释

“部门否认居民退出协商是由于补偿下降。”

若文本确实呈现该被否定解释，则建立`polarity=denied`的Claim。它不得与`polarity=affirmed`的同内容Claim归入同一Canonical Claim Group。

### 12.5 客观真因不可标注

标注员根据背景知识认为某政策造成居民不满，但文档没有任何主体提出该解释时，不得创建正式Claim。

## 13. 标注分歧与裁决

A、B标注员分别独立标注文档级Effect、Attribution Claim和Evidence Span；LLM预标注只作为候选，未经人工明确确认不得进入Gold。A、B不填写`canonical_effect_id`或`canonical_claim_group_id`。两者一致的文档级结果直接进入待导出集合，只有分歧项交给C标注员裁决。

Fusion Gold是独立的pair-label任务，不直接填写Canonical ID，也不得调用APCF预测。Pilot在同Event、仅应用不可违反类型约束的pair universe内做近似穷举审计：A/B独立标注Effect/Claim pair的semantic label，C只处理分歧与歧义。由Gold equivalent pair计算Candidate Blocking Recall；低于0.98时扩大blocker并重新审计，达标后在首次Formal推理前冻结。禁止依据Formal Fusion结果继续修改blocking。

以下情况必须进入裁决：

- Effect是否应拆分存在分歧；
- EffectHolder Category或AttributionHolder Category无法可靠确定；
- `implicit`关系依赖较强推断；
- Explanation跨度或规范化表达差异影响命题含义；
- `additional`与`explicitly_contradicted`存在分歧；
- `primary_source_id`谱系无法由现有来源链确认。

裁决时只使用冻结文本、事件登记信息和来源继承记录，不使用未记录的个人背景知识。

试标阶段至少检查：

```text
Effect边界一致性
Effect类型一致性
Stakeholder Category一致性
关系类型一致性
AttributionHolder Category一致性
explicit/implicit一致性
polarity一致性
证据Span一致性
Claim Pair关系一致性
```

如果`implicit`关系、AttributionHolder或证据跨度的一致性无法达到可接受水平，应先修订示例和边界规则，再扩大数据规模。

## 14. 实验口径约束

### 14.1 原EpiSOA基线

所有方法进入评价时统一输出公共评价Schema；原EpiSOA的原始字段按下列方式映射：

```text
Stakeholder -> Stakeholder Category
Stance -> Stance封闭标签
Emotion -> Emotion封闭标签
Action -> 规范化短语
Rationale -> Explanation
EvidenceIDs -> Evidence Links
```

原方法不能产生的AttributionHolder或字段级验证字段按预注册的缺失值规则保留，不得由评测适配层补推断。该基线必须能够输出Rationale和EvidenceIDs以形成有效比较，但其方法本身不包含：

```text
类型化成因关系约束
EffectHolder与AttributionHolder双主体归属
字段级证据验证
```

Main comparison methods固定为：

1. Long-context Event-level LLM；
2. Long-context Event-level LLM + Evidence Requirement；
3. Direct Explanation–Effect Pair Classification；
4. Original EpiSOA；
5. EpiSOA-EA。

完整Event-Dossier architecture comparison只包含Long-context、Long-context + Evidence和EpiSOA-EA。Direct Pair只在固定Gold Candidate Set上评价Relation Decision；Original EpiSOA是historical baseline，只评价其能忠实产生的字段，不补造Dossier输出。旧的逐文档One-shot LLM不再作为核心主基线。

v1.5不引入LightRAG、EventRAG、GraphRAG或相应依赖，也不在M5增加RAG-style方法模块。

所有方法对`Stakeholder Category`、`Stance`和`Emotion`使用同一封闭标签空间、公共评价Schema和评价映射规则，并共享相同的Formal Events、Document、冻结正文、ID、Gold、规范化器和评价代码。LLM Pairwise与APCF必须共享同一candidate pairs、基础LLM、基础Prompt、temperature、解码和semantic pair judgment资源；Claim候选集不得随预测CanonicalEffect改变，Effect membership只进入后续merge constraint。Long-context与EpiSOA-EA使用同一基础LLM；60个Formal Event冻结后、首次推理前用官方Tokenizer完成容量预检并冻结model/version。不得静默截断；`capacity_failure`单独报告且阻断不完整主表。

自然语言字符串不直接用于主要类别F1。例如“业主”“小区居民”“业主代表”均规范为`affected_public`；“不接受”“反对”“不同意”均规范为`oppose`。主要指标比较规范化类别，而不是原文字符串Exact Match。

### 14.2 关系与端到端指标

- `Relation Decision Macro-F1`必须在所有方法共享的固定金标准候选集上计算；
- 标签固定为`stance_rationale`、`emotion_trigger`、`action_motivation`和`no_relation`；
- 不得让不同方法使用各自生成的候选集合计算Relation Decision Macro-F1；
- 完整流程从文本到正式Claim的结果使用`Attribution Claim F1`评价；
- 候选生成错误和关系判断错误应分别报告，不得混为同一个关系分类指标。

主体、立场和情绪的主要指标为：

```text
Stakeholder Category F1
AttributionHolder Category Accuracy
Holder Category Mismatch Rate
Stance Macro-F1
Emotion Macro-F1
```

具体人物级Entity F1不作为主要指标。`Attribution Claim F1`基于规范化后的`Stakeholder Category`、`Effect Type`、`Effect Value`、`Relation Type`和`AttributionHolder Category`，并结合Explanation语义匹配或Gold规范化结果；不得仅因主体原文称谓不同而判整条Claim不匹配。Action和Explanation继续按开放文本及字段级Evidence Span评价。

Explanation不要求`normalized_explanation`字符串完全一致：Gold与预测Span在同一文档中的中文字符级F1达到0.5，或二者命中所有方法共享的冻结、版本化语义等价规则，即可匹配；评价输出必须记录采用的匹配路径。`Holder Category Mismatch Rate`在其余Claim字段及Explanation已对齐的样本上，统计预测的EffectHolder/AttributionHolder“同类或异类”关系与Gold不一致的比例。False Acceptance统计Gold不应晋升却被判为`verified`的比例，False Rejection统计Gold应晋升却被判为`insufficient/rejected`的比例，二者使用同一固定验证候选集。

`Cross-document Attribution Contamination Rate`统计被评估预测Claim中，将不同Document的EffectHolder、Explanation、AttributionHolder或Evidence错误拼接成任何原文都不存在的归属关系的比例。分母为纳入该项统一复核的预测Claim，分子为确认发生跨文档拼接的Claim，数值越低越好。所有方法使用相同Gold和裁决规则，重点比较Long-context Event-level LLM与EpiSOA-EA。

例：D1记载“居民说反对是因为补偿低”，D2记载“政府认为居民是因为政策理解不足”。若预测为“居民表示自己因为政策理解不足而反对”，则把D2的外部解释错误变成居民自身解释，应计为跨文档归属污染。准确保留不同Claim各自的提出者、来源和Evidence后进行事件级并列组织，不计为污染。

### 14.3 核心消融

正式消融只保留：

```text
w/o Type Constraint
w/o Dual Attribution
w/o Field-Level Verification
```

每项只改变一个对应机制，其余Formal Event、Document、Gold、Prompt、底层模型和评价保持一致；不得新增其他消融或方法模块。

## 15. 正式数据文件

正式标注数据包括：

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

过程性数据包括：

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

`no_relation`和`insufficient/rejected`记录只保存在过程性数据中，不进入正式Claim表。`verification_diagnostics.jsonl`保存所有验证尝试，包括最终晋升的`verified`记录。

正式Canonical与Dossier文件只物化APCF结果；Exact、Embedding和LLM Pairwise的融合输出留在各自隔离的实验目录，不得覆盖正式APCF文件。

上述JSONL是Event Dossier的序列化存储形式。事件级组装后，Event Opinion Graph必须能够组织Event、Stage、Document、Source、Effect、CanonicalEffect、AttributionClaim、CanonicalClaimGroup、ClaimPairRelation和EvidenceSpan。标注员负责来源级Effect、Claim和Evidence以及必要裁决，不需要手工绘制图；确定性程序依据已验证记录及跨文件引用物化图结构。图中不得创建`Explanation --causes--> Effect`等客观因果边。

## 16. Pilot与Formal数据设计

### 16.1 数据角色与规模

数据集严格区分Pilot与Formal两部分：

```text
6 Pilot Events
+
60 Formal Events
=
66 total processed events
```

6个Pilot Event分别来自城市更新、教育、医疗、公共安全、城市交通和数字治理，每领域1个。Pilot仅用于M5试标、标注规范验证以及Prompt和流程调试，不得作为正式Test数据，也不得进入正式论文指标。

单个具体多来源公共事件是Event Dossier的实际应用单位。60个Formal Event构成跨治理情境检验方法稳定性的Benchmark corpus，不意味着每个Event只产生一条结果，也不要求论文逐一解释60个事件；每个Event内部均可包含多个Document、Effect、Claim和Evidence Span。

正式Gold与Main comparison methods实验只使用60个Formal Event，按六领域均衡配置：

```text
城市更新：10
教育：10
医疗：10
公共安全：10
城市交通：10
数字治理：10
```

每个Formal Event保留约6至8篇有效Document，预计形成约360至480篇正式Document；不要求各事件产生相同数量的Effect、Claim、Relation Candidate或Evidence Span。

F1的直接评价实例是Effect、Claim、Relation Candidate和Evidence Span等，但同一Event内实例存在聚类相关性，因此Event是高层独立抽样单位。每领域10个事件用于增强跨事件稳定性观察；不扩展至100个Formal Event，以避免约600至800篇Document造成过高双人Gold标注成本。

### 16.2 事件选择与冻结

Pilot和Formal Event均采用`criterion-based purposive sampling + maximum variation sampling`。Formal Event必须在正式Gold构建和正式实验前冻结，不得根据模型表现选择、替换或排除。每领域10个事件只支持领域级描述性结果，不代表该领域总体，也不得据领域间F1差异作强因果或泛化结论。

### 16.3 M5试标停止条件

在扩大到正式数据收集前，应完成固定的6个Pilot Event试标，并确认：

1. 两类阶段字段能够稳定区分；
2. EffectHolder Category与AttributionHolder Category能够分别标注；
3. 显式与隐式关系具备可复现边界；
4. 证据Span能够绑定到冻结正文；
5. `primary_source_id`来源谱系与`derivation_type`能够稳定判断；
6. 正负候选数量足以支持固定候选集上的Relation Decision Macro-F1；
7. Canonical Claim Group归并及Claim Pair判断达到预注册门槛；
8. Effect与Claim Candidate Blocking Recall均达到0.98。

最低一致性门槛在正式试标前固定为：

- Stakeholder Category和AttributionHolder Category：类别一致率不低于0.80；
- Effect类型和Relation Decision：Cohen's kappa（两名标注员）或Fleiss' kappa（三名及以上标注员）不低于0.80；
- implicit关系的Relation Decision：一致性不低于0.70；
- Evidence Span：中文字符级F1不低于0.75。

implicit关系的一致性同样使用Cohen's kappa或Fleiss' kappa；Evidence Span使用标注员两两字符级F1。任一核心门槛未达到时，先修订规范并用新的独立样本重新试标，不得扩大正式数据规模或事后降低门槛。

未满足上述条件时，只修订标注规范和示例，不增加新的方法模块。

工程正确性必须100%满足：无hard-constraint violation、无Gold循环依赖、Span全部可回读、Dossier provenance无断链、确定性转载测试Overcount为0。False Merge、Pairwise F1和Conflict Preservation只作Pilot描述性比较；相对最佳方法F1下降0.05只是工程阈值。若Gold contradiction pair不足，Conflict Preservation门禁记为`NA`并报告原始样本数，不得因无样本自动记为1.0。

Pilot通过后，阶段流程为：

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

### 16.4 正式评价聚合

正式评价采用三层报告：

1. **实例级总体指标：** 对60个Formal Event中的相应评价实例统一汇总计算Stakeholder Category F1、Stance Macro-F1、Emotion Macro-F1、Relation Decision Macro-F1、Attribution Claim F1、Evidence Span F1、Cross-document Attribution Contamination Rate及其他已冻结指标，作为论文主要结果；Pilot实例不得混入。
2. **事件级稳健性：** 分别计算每个Event的主要指标，报告event-level mean、median及离散程度。某Event没有相应Gold评价实例时记为`NA`而不是0，并报告有效事件数。
3. **事件聚类Bootstrap：** 以Event为重采样单位，每次从60个Formal Event中有放回抽取60个Event，按抽中次数整体纳入各Event的全部实例并重新计算指标；在正式实验前从1000至5000次范围内预注册重复次数，并为主要指标报告95%置信区间。

EpiSOA-EA与各基线比较时使用配对Event Bootstrap：所有方法使用完全相同的Formal Event、Document和Gold，每次对同一批Event进行配对重采样，并报告方法指标差及其95%置信区间。不得把所有Claim视为独立样本进行Bootstrap。

### 16.5 Event Dossier Case Study

从Formal Events中选择1–2个结构丰富的事件展示实际档案价值。选择标准必须在查看Main comparison methods结果前冻结，例如来源类型多样、阶段覆盖较完整、包含多个Stakeholder和多种Explanation Attribution；不得因为EpiSOA-EA在该事件表现较好而选择。

案例至少分析：Stakeholder–Effect结构；EffectHolder与AttributionHolder及self/external attribution差异；official、media、affected_public、expert等来源/主体的Claim结构；以及`trigger`至`follow_up`的Stage演化。Case Study只描述证据可追溯的信息结构，不作客观因果推断，也不替代正式60-event总体评价。
