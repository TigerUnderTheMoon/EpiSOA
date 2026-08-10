# M5 Gold标注模板使用说明

模板目录：`docs/templates/m5/`。实际工作表优先由`prepare-ea-gold`生成；模板仅定义字段与人工新增规则，不是Gold数据。

## A/B来源级标注

每位标注员独立维护`document_annotations.csv`。一条候选可以`accept/revise/reject`；原候选没有覆盖的来源级Effect、Claim或Evidence必须使用`add`，并在`human_payload_json`中写入完整、可通过Pydantic Schema验证的JSON。

人工新增行必须满足：

```text
annotation_key = item_type:record_id
candidate_origin = human_added
candidate_payload_json = 空
human_decision = add
human_payload_json = 完整来源级JSON
review_status = completed
annotator_id = A或B
```

不得在任何人工payload中填写`canonical_effect_id`或`canonical_claim_group_id`。Effect的`holder_surface`必须有Evidence；Claim的`attribution_holder_surface`可为`null`，非null时必须有对应Evidence。

## C文档级裁决

C只接收A/B不一致项。`c_decision`只能为`choose_a`、`choose_b`、`custom`或`reject`；`custom`必须提供完整`c_payload_json`。C不得重标A/B已经一致的文档级记录。

## Fusion Pair

Fusion Pair实际文件为JSONL。Effect标签限于`equivalent_effect/distinct_effect/unresolved`；Claim标签限于`equivalent_explanation/additional/explicitly_contradicted/unresolved`。A/B独立标注，C只处理分歧。语义等价与merge compatibility不是同一标签；AttributionHolder不兼容由程序生成`cannot_link`，不能把语义标签改成不等价来代替。

## 推荐命令

```text
python -m episoa.cli prepare-ea-gold --config configs/ea_pilot.yaml --phase initialize
python -m episoa.cli prepare-ea-gold --config configs/ea_pilot.yaml --phase disagreements
python -m episoa.cli prepare-ea-gold --config configs/ea_pilot.yaml --phase export
python -m episoa.cli prepare-ea-gold --config configs/ea_pilot.yaml --phase fusion_initialize
python -m episoa.cli prepare-ea-gold --config configs/ea_pilot.yaml --phase fusion_disagreements
python -m episoa.cli prepare-ea-gold --config configs/ea_pilot.yaml --phase fusion_export --blocked-pairs <blocking-audit.json>
```

每个阶段运行前保留输入hash和工作表副本。导出的Gold必须通过外键、Span、来源、重复项和Canonical循环依赖检查。
