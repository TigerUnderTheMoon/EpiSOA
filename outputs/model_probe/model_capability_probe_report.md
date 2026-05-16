# Model Capability Probe Report

## Design
- 10 events are selected from P0 zero-prediction, high-gold-count, and normal events.
- Each event uses oracle gold evidence IDs only; gold tuple text is never passed to the model.
- Graph and event-chain ranking are disabled; the prompt uses evidence-only extraction.

## Events
- E001: p0_zero_prediction / 广州市白云区三元里村城中村改造补偿安置方案发布事件
- E002: p0_zero_prediction / 上海市浦东新区唐镇小湾村、暮二村城中村改造签约与租客迁徙事件
- E010: p0_zero_prediction / 衢州市柯城区百家坊未来社区安置房延期交付事件
- E032: p0_zero_prediction / 广东梅大高速茶阳路段“5·1”塌方灾害
- E011: high_gold_count / 江西工业职业技术学院“鼠头鸭脖”食品安全事件
- E012: high_gold_count / 昆明市官渡区长丰学校食堂“臭肉”事件
- E019: high_gold_count / 美吉姆北京多门店停业退费争议事件
- E016: normal / 河南省方城县英才学校宿舍火灾事件
- E018: normal / 暨南大学石牌校区宿舍霉菌与甲醛争议事件
- E027: normal / 上海浦东医院周边“医托”诈骗团伙案

## Aggregate Results
- deepseek-v4-flash: F1=0.2593, P=0.5385, R=0.1707, tuples=13, zero_events=5, sentiment_acc=0.5714
- kimi-k2.6: F1=0.3438, P=0.4783, R=0.2683, tuples=23, zero_events=2, sentiment_acc=0.7273

## Required Answers
- If current-model F1 remains low under oracle evidence, the likely bottleneck shifts to prompt/extraction/gold consistency/evaluation.
- If a stronger model is configured and improves materially, current model capacity is a contributor.
- If the stronger model also remains low, prioritize gold cleanup, prompt redesign, and metric audit before scaling API spend.
