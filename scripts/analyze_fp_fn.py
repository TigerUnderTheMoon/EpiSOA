"""Analyze false positives and false negatives for precision/recall diagnosis."""
import json
from collections import Counter
from episoa.evaluation.metrics import match_tuples, filter_predictions_to_gold_events
from episoa.evaluation.evaluate_main import normalize_for_matching
from episoa.data.schema import GoldTuple, PredictionTuple

# Load gold and predictions
gold = []
with open('data/pubevent_soa_lite/human_gold_v2/human_gold_tuples_v2.jsonl', encoding='utf-8') as f:
    for line in f:
        gold.append(GoldTuple(**json.loads(line)))

preds = []
with open('outputs/runs_human_gold_v2/pubevent-soa-lite-human-gold-v2-paper/candidate_soa_tuples.jsonl', encoding='utf-8') as f:
    for line in f:
        preds.append(PredictionTuple(**json.loads(line)))

# Normalize for matching
eval_gold, eval_pred = normalize_for_matching(gold, preds)

# Filter to gold events
scored, excluded, excluded_events = filter_predictions_to_gold_events(eval_gold, eval_pred)
print(f'Gold tuples: {len(eval_gold)}')
print(f'Scored predictions: {len(scored)}')
print(f'Excluded predictions: {len(excluded)}')
print(f'Excluded events: {excluded_events}')

# Run matching at threshold 0.3
result = match_tuples(eval_gold, scored, matcher='semantic', threshold=0.3)
matched = len(result['matches'])
unmatched_gold = len(result['unmatched_gold_indices'])
unmatched_pred = len(result['unmatched_pred_indices'])
print(f'\nMatched pairs: {matched}')
print(f'Unmatched gold (false negatives): {unmatched_gold}')
print(f'Unmatched pred (false positives): {unmatched_pred}')
print(f'Precision@0.3: {matched / len(scored):.4f}')
print(f'Recall@0.3: {matched / len(eval_gold):.4f}')

# Analyze false positives (unmatched predictions)
print('\n=== FALSE POSITIVES (unmatched predictions) ===')
false_positives = []
for idx in result['unmatched_pred_indices']:
    pred = scored[idx]
    false_positives.append({
        'event_id': pred.event_id,
        'stakeholder': pred.stakeholder,
        'opinion': pred.opinion[:60] if pred.opinion else '',
        'sentiment': pred.sentiment,
        'support_label': pred.support_label if hasattr(pred, 'support_label') else '',
    })

# FP per event
event_fp_counts = Counter(fp['event_id'] for fp in false_positives)
print(f'\nFalse positives per event (top 10):')
for event_id, count in event_fp_counts.most_common(10):
    print(f'  {event_id}: {count} FPs')

# FP by stakeholder
sh_fp_counts = Counter(fp['stakeholder'] for fp in false_positives)
print(f'\nFalse positives by stakeholder (top 15):')
for sh, count in sh_fp_counts.most_common(15):
    print(f'  {sh}: {count}')

# Sample FPs
print(f'\nSample false positives (first 25):')
for i, fp in enumerate(false_positives[:25]):
    print(f'  {i+1}. [{fp["event_id"]}] {fp["stakeholder"]}: {fp["opinion"]} ({fp["sentiment"]})')

# Analyze false negatives (unmatched gold)
print('\n=== FALSE NEGATIVES (unmatched gold) ===')
false_negatives = []
for idx in result['unmatched_gold_indices']:
    g = eval_gold[idx]
    false_negatives.append({
        'event_id': g.event_id,
        'stakeholder': g.stakeholder,
        'opinion': g.opinion[:60] if g.opinion else '',
        'sentiment': g.sentiment,
    })

# FN per event
event_fn_counts = Counter(fn['event_id'] for fn in false_negatives)
print(f'\nFalse negatives per event (top 10):')
for event_id, count in event_fn_counts.most_common(10):
    print(f'  {event_id}: {count} FNs')

# FN by stakeholder
sh_fn_counts = Counter(fn['stakeholder'] for fn in false_negatives)
print(f'\nFalse negatives by stakeholder (top 15):')
for sh, count in sh_fn_counts.most_common(15):
    print(f'  {sh}: {count}')

# Sample FNs
print(f'\nSample false negatives (first 25):')
for i, fn in enumerate(false_negatives[:25]):
    print(f'  {i+1}. [{fn["event_id"]}] {fn["stakeholder"]}: {fn["opinion"]} ({fn["sentiment"]})')

# Generic label analysis
GENERIC_LABELS = {"居民/公众_泛指", "公众", "网友", "社会", "社会公众", "社会舆论", "公众/网友", "公众质疑者"}
generic_fps = [fp for fp in false_positives if fp['stakeholder'] in GENERIC_LABELS]
generic_fns = [fn for fn in false_negatives if fn['stakeholder'] in GENERIC_LABELS]
print(f'\n=== GENERIC LABEL ANALYSIS ===')
print(f'Generic label FPs: {len(generic_fps)}/{len(false_positives)} ({100*len(generic_fps)/len(false_positives):.1f}%)')
print(f'Generic label FNs: {len(generic_fns)}/{len(false_negatives)} ({100*len(generic_fns)/len(false_negatives):.1f}%)')

# Check if FPs are near-matches (score 0.2-0.29)
print('\n=== NEAR-MISS ANALYSIS (score 0.2-0.29) ===')
near_miss_pairs = []
for gp_idx, gp in enumerate(eval_gold):
    for pp_idx, pp in enumerate(scored):
        if gp.event_id != pp.event_id:
            continue
        score, fields = tuple_pair_score(gp, pp, matcher='semantic', field_weights={'stakeholder': 0.5, 'opinion': 0.5})
        if 0.2 <= score < 0.3:
            near_miss_pairs.append((gp_idx, pp_idx, score, fields))

print(f'Near-miss pairs (score 0.2-0.29): {len(near_miss_pairs)}')
near_miss_pairs.sort(key=lambda x: -x[2])
for gp_idx, pp_idx, score, fields in near_miss_pairs[:10]:
    gp = eval_gold[gp_idx]
    pp = scored[pp_idx]
    sh_sim = fields.get('stakeholder', 0)
    op_sim = fields.get('opinion', 0)
    print(f'  score={score:.3f} sh_sim={sh_sim:.3f} op_sim={op_sim:.3f}')
    print(f'    GOLD: [{gp.event_id}] {gp.stakeholder}: {gp.opinion[:50]}')
    print(f'    PRED: [{pp.event_id}] {pp.stakeholder}: {pp.opinion[:50]}')