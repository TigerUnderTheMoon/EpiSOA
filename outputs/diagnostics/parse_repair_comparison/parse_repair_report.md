# P0 Parse Repair 实验结果

## 实验设置

- 对照组（old）：`outputs/runs/ablation_full/`，max_tokens=3000，max_retries=1，无 malformed JSON retry
- 实验组（new）：`outputs/runs_p0_parse_repair/ablation_full/`，max_tokens=8000，max_retries=2，增加 malformed JSON retry

## 核心指标对比

| 指标 | Old (full) | New (P0) | Delta |
|---|---|---|---|
| Num-Gold | 188 | 188 | +0 |
| Num-Tuples | 65 | 97 | +32 |
| Tuple-F1-soft | 0.3083 | 0.3860 | +0.0777 |
| Tuple-Precision | 0.6000 | 0.5670 | -0.0330 |
| Tuple-Recall | 0.2074 | 0.2926 | +0.0852 |
| Sentiment-Acc | 0.6667 | 0.7091 | +0.0424 |

## 解析稳定性对比

| 指标 | Old | New |
|---|---|---|
| 零预测事件数 | 17 | 8 |
| parse 失败事件数 | 10 | 0 |
| empty_llm_content 事件数 | 6 | 0 |
| incomplete/malformed JSON 事件数 | 4 | 0 |
| parse 修复事件数 | — | 10 |

## parse 修复事件明细

| event_id | old_parse_error | new_pred_count | gold_tuple_count |
|---|---|---|---|
| E011 | empty_llm_content | 4 | 5 |
| E012 | incomplete_or_malformed_json | 4 | 5 |
| E015 | incomplete_or_malformed_json | 2 | 3 |
| E019 | empty_llm_content | 2 | 5 |
| E020 | incomplete_or_malformed_json | 3 | 5 |
| E025 | empty_llm_content | 2 | 3 |
| E026 | incomplete_or_malformed_json | 3 | 3 |
| E036 | empty_llm_content | 3 | 4 |
| E041 | empty_llm_content | 4 | 5 |
| E043 | empty_llm_content | 3 | 4 |

## 诊断结论

1. ✅ empty_llm_content 从 6 降至 0，max_tokens 提升有效减少了空响应。
2. ✅ incomplete/malformed JSON 从 4 降至 0，max_tokens+retry 修复有效。
3. ✅ 零预测事件数从 17 降至 8，parse 修复直接减少了零输出事件。
4. ✅ Num-Tuples 从 65 升至 97（+32）。
5. ✅ Tuple-F1-soft 从 0.3083 升至 0.3860（+0.0777）。
6. ❌ 当前 max_tokens=8000 已足够，无需继续增大。
7. ⚠️ 零预测事件已大幅减少，可先稳定 P0 修复再考虑 P1。

## 是否保留 schema_attributor.py retry 修复

✅ 建议保留。新增的 malformed JSON retry 修复了 10 个事件，无负面效果。
