from episoa.evaluation.evaluate_main import evaluate_main, normalize_for_matching
from episoa.evaluation.metrics import two_stage_tuple_f1, match_tuples, filter_predictions_to_gold_events
from episoa.data.schema import GoldTuple, PredictionTuple
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

gold = []
with open('data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl', encoding='utf-8') as f:
    for line in f:
        gold.append(GoldTuple(**json.loads(line)))

preds = []
with open('outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/candidate_soa_tuples.jsonl', encoding='utf-8') as f:
    for line in f:
        preds.append(PredictionTuple(**json.loads(line)))

# Method 1: two_stage with normalize=True
r025 = two_stage_tuple_f1(gold, preds, normalize=True, matcher='semantic', threshold=0.25)
print('two_stage normalize=True t=0.25: F1=%.4f P=%.4f R=%.4f' % (r025['f1'], r025['precision'], r025['recall']))

# Method 2: two_stage with normalize=False
r025b = two_stage_tuple_f1(gold, preds, normalize=False, matcher='semantic', threshold=0.25)
print('two_stage normalize=False t=0.25: F1=%.4f P=%.4f R=%.4f' % (r025b['f1'], r025b['precision'], r025b['recall']))

# Method 3: manual with normalize_for_matching
eval_gold, eval_pred = normalize_for_matching(gold, preds)
scored, excluded, excluded_events = filter_predictions_to_gold_events(eval_gold, eval_pred)
result = match_tuples(eval_gold, scored, matcher='semantic', threshold=0.25, field_weights={'stakeholder': 0.3, 'opinion': 0.7})
m = len(result['matches'])
p = m / len(scored)
r = m / len(eval_gold)
f1 = 2*p*r/(p+r) if (p+r) > 0 else 0
print('manual normalize_for_matching t=0.25 sh=0.3/op=0.7: F1=%.4f P=%.4f R=%.4f matches=%d' % (f1, p, r, m))