import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from episoa.evaluation.metrics import match_tuples, filter_predictions_to_gold_events
from episoa.evaluation.evaluate_main import evaluate_main, normalize_for_matching
from episoa.data.schema import GoldTuple, PredictionTuple

gold = []
with open('data/pubevent_soa_lite/human_gold_tuples_v2.jsonl'.replace('human_gold_tuples', 'human_gold_v2/human_gold_tuples'), encoding='utf-8') as f:
    pass

gold = []
with open('data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl', encoding='utf-8') as f:
    for line in f:
        gold.append(GoldTuple(**json.loads(line)))

preds = []
with open('outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/candidate_soa_tuples.jsonl', encoding='utf-8') as f:
    for line in f:
        preds.append(PredictionTuple(**json.loads(line)))

m = evaluate_main(gold, preds, verifier_enabled=False)
print('=== UPDATED METRICS (after alias expansion) ===')
for key in ['Tuple-F1-semantic@0.3', 'Tuple-Precision-semantic@0.3', 'Tuple-Recall-semantic@0.3',
            'Stakeholder-Recall-semantic@0.3', 'Opinion-Recall-semantic@0.3',
            'Tuple-F1-semantic@0.5', 'Num-Tuples', 'Num-Gold']:
    print(f'{key}: {m.get(key, "N/A")}')

eval_gold, eval_pred = normalize_for_matching(gold, preds)
scored, excluded, excluded_events = filter_predictions_to_gold_events(eval_gold, eval_pred)
print('\nThreshold sweep (semantic, sh=0.3/op=0.7):')
for t in [0.20, 0.25, 0.30, 0.35, 0.40]:
    result = match_tuples(eval_gold, scored, matcher='semantic', threshold=t, field_weights={'stakeholder': 0.3, 'opinion': 0.7})
    m_t = len(result['matches'])
    p_t = m_t / len(scored)
    r_t = m_t / len(eval_gold)
    f1_t = 2 * p_t * r_t / (p_t + r_t) if (p_t + r_t) > 0 else 0
    print(f'  t={t:.2f}: P={p_t:.4f} R={r_t:.4f} F1={f1_t:.4f} matches={m_t}')