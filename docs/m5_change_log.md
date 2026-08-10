# EpiSOA-EA M5 Change Log

冻结基线：`EpiSOA-EA-v1.5-prepilot`
规则：M5开始后所有问题先登记，不得静默修改实现、Schema、Prompt、事件或评价。

## 状态枚举

- `open`：已复现，待决定；
- `clarification`：只需规范文字澄清；
- `patch_approved`：局部修复获准，必须升级patch版本并重跑受影响阶段；
- `method_revision`：结构性问题，升级v1.6；
- `closed_no_change`：非缺陷或无需修改。

## 记录模板

| Issue ID | Date | Event/Document | Layer | Reproduction artifact | Severity | Decision | Version impact | Rerun scope | Status |
|---|---|---|---|---|---|---|---|---|---|

Layer限定为：`collection`、`document`、`effect`、`claim`、`evidence`、`verification`、`blocking`、`fusion`、`dossier`、`evaluation`或`infrastructure`。

## 冻结时已知事项

| Issue ID | Date | Event/Document | Layer | Reproduction artifact | Severity | Decision | Version impact | Rerun scope | Status |
|---|---|---|---|---|---|---|---|---|---|
| M5-LEGACY-001 | 2026-08-10 | legacy workspace | infrastructure | 3 tests listed in `m5_pilot_protocol.md` | non-EA | missing ignored historical fixtures; do not fabricate | none | none | closed_no_change |
