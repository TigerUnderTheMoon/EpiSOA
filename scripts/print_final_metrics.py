from episoa.evaluation.evaluate_main import evaluate_main
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

m = evaluate_main(gold, preds, verifier_enabled=False)
print('=== FINAL METRICS ===')
for key in ['Tuple-F1-semantic@0.25', 'Tuple-Precision-semantic@0.25', 'Tuple-Recall-semantic@0.25',
            'Tuple-F1-semantic@0.3', 'Tuple-Precision-semantic@0.3', 'Tuple-Recall-semantic@0.3',
            'Tuple-F1-semantic@0.5', 'Tuple-Precision-semantic@0.5', 'Tuple-Recall-semantic@0.5',
            'Stakeholder-Recall-semantic@0.25', 'Opinion-Recall-semantic@0.25',
            'Stakeholder-Recall-semantic@0.3', 'Opinion-Recall-semantic@0.3',
            'Num-Tuples', 'Num-Gold']:
    val = m.get(key, 'N/A')
    print(f'{key}: {val}')

import pathlib
run_dir = pathlib.Path('outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper')
with open(run_dir / 'metrics.json', 'w', encoding='utf-8') as f:
    json.dump(m, f, ensure_ascii=False, indent=2)
print('\nmetrics.json updated')