事件：{event_name}

Gold 元组：
{gold_tuples_text}

Pred 元组：
{pred_tuples_text}

对每个 Pred 元组，判断它与哪个 Gold 元组语义最匹配（或都不匹配），输出 JSON：
{{"matches": [{{"pred_index": 0, "gold_index": 1, "match": true, "reason": "简短理由"}}, ...]}}

注意：pred_index 和 gold_index 从 0 开始。如果一个 pred 不匹配任何 gold，gold_index 设为 -1。
