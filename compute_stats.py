import json
from collections import Counter, defaultdict
from datetime import datetime

# ===== 1. Gold Tuple Sentiment Distribution =====
print("=" * 60)
print("1. GOLD TUPLE SENTIMENT DISTRIBUTION")
print("=" * 60)

tuples_path = r'D:\Workplace\EpiSOA\data\pubevent_soa_lite\human_gold_v2\human_gold_tuples_v2.jsonl'
sentiments = []
event_tuples = defaultdict(list)

with open(tuples_path, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        s = d.get('sentiment', 'unknown')
        sentiments.append(s)
        event_tuples[d.get('event_id', 'unknown')].append(s)

sentiment_counts = Counter(sentiments)
total_tuples = len(sentiments)
num_events = len(event_tuples)

print(f'Total tuples: {total_tuples}')
print(f'Total events with tuples: {num_events}')
print(f'Tuples per event (avg): {total_tuples/num_events:.1f}')
print()
print('Global sentiment distribution:')
for s in ['positive', 'negative', 'neutral', 'mixed']:
    c = sentiment_counts.get(s, 0)
    pct = c / total_tuples * 100
    print(f'  {s:>10s}: {c:4d} ({pct:5.1f}%)')
for s, c in sentiment_counts.most_common():
    if s not in ['positive', 'negative', 'neutral', 'mixed']:
        print(f'  {s:>10s}: {c:4d} ({c/total_tuples*100:5.1f}%)')

event_sentiment_ctrs = {eid: Counter(slist) for eid, slist in event_tuples.items()}
print()
print('Per-event avg sentiment distribution:')
for s in ['positive', 'negative', 'neutral', 'mixed']:
    total_per_s = sum(eb.get(s, 0) for eb in event_sentiment_ctrs.values())
    avg_per_event = total_per_s / num_events
    print(f'  {s:>10s}: avg {avg_per_event:.2f} per event (total {total_per_s})')

# ===== 2. Event Type/Domain Distribution =====
print()
print("=" * 60)
print("2. EVENT DOMAIN/TYPE DISTRIBUTION")
print("=" * 60)

events_path = r'D:\Workplace\EpiSOA\data\pubevent_soa_lite\events.jsonl'
domains = []
event_types = []
splits = []
event_ids = []

with open(events_path, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        domains.append(d.get('domain', 'unknown'))
        event_types.append(d.get('event_type', 'unknown'))
        splits.append(d.get('split', 'unknown'))
        event_ids.append(d.get('event_id', 'unknown'))

domain_counts = Counter(domains)
etype_counts = Counter(event_types)
split_counts = Counter(splits)

print(f'Total events: {len(event_ids)}')
print()
print('Domain distribution:')
for dom, count in domain_counts.most_common():
    pct = count / len(event_ids) * 100
    print(f'  {dom:>30s}: {count:3d} ({pct:5.1f}%)')

print()
print('Event type distribution:')
for et, count in etype_counts.most_common():
    pct = count / len(event_ids) * 100
    print(f'  {et:>30s}: {count:3d} ({pct:5.1f}%)')

print()
print('Split distribution:')
for sp, count in split_counts.most_common():
    pct = count / len(event_ids) * 100
    print(f'  {sp:>30s}: {count:3d} ({pct:5.1f}%)')

# ===== 3. Evidence Time Span =====
print()
print("=" * 60)
print("3. EVIDENCE TIME SPAN")
print("=" * 60)

evidence_path = r'D:\Workplace\EpiSOA\data\pubevent_soa_lite\evidence_v3_repaired_plus_low37.jsonl'
dates = []
null_count = 0
total = 0
source_types = Counter()
events_with_evidence = set()
publish_times = []

with open(evidence_path, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        total += 1
        source_types[d.get('source', 'unknown')] += 1
        events_with_evidence.add(d.get('event_id'))

        pt = d.get('publish_time')
        if pt is None:
            null_count += 1
            continue
        try:
            pt_clean = pt.replace('Z', '+00:00')
            dt = datetime.fromisoformat(pt_clean)
            dates.append(dt)
        except Exception:
            null_count += 1

print(f'Total evidence items: {total}')
print(f'Events with evidence: {len(events_with_evidence)}')
print(f'Evidence per event (avg): {total/len(events_with_evidence):.1f}')
print(f'Items with valid publish_time: {len(dates)}')
print(f'Items with null/invalid publish_time: {null_count} ({null_count/total*100:.1f}%)')

print()
print('Evidence source distribution:')
for src, count in source_types.most_common():
    pct = count / total * 100
    print(f'  {src:>20s}: {count:4d} ({pct:5.1f}%)')

if dates:
    dates.sort()
    earliest = dates[0]
    latest = dates[-1]
    span_days = (latest - earliest).days
    span_months = span_days / 30.44
    span_years = span_days / 365.25
    print()
    print(f'Earliest publish_time: {earliest.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'Latest publish_time:   {latest.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'Time span:              {span_days} days ({span_months:.1f} months / {span_years:.2f} years)')

# ===== 4. Gold Chain Stage Distribution =====
print()
print("=" * 60)
print("4. GOLD CHAIN STAGE DISTRIBUTION")
print("=" * 60)

chains_path = r'D:\Workplace\EpiSOA\data\pubevent_soa_lite\human_gold_v2\human_gold_event_chains_v2.jsonl'

# Load event temporal stages mapping
event_stages = {}
with open(events_path, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        event_stages[d['event_id']] = d.get('temporal_stages', [])

total_chains = 0
stage_counts = Counter()
stage_per_position = defaultdict(Counter)
chains_per_event = Counter()
event_stage_coverage = defaultdict(lambda: {'total_chains': 0, 'stages_present': set()})
unmatched_positions = 0

with open(chains_path, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        total_chains += 1
        eid = d.get('event_id', '')
        chain = d.get('event_chain', [])
        chains_per_event[eid] += 1

        ts = event_stages.get(eid, [])
        for pos, stage_desc in enumerate(chain):
            stage_name = ts[pos] if pos < len(ts) else f'position_{pos}'
            stage_counts[stage_name] += 1
            stage_per_position[pos][stage_name] += 1
            event_stage_coverage[eid]['stages_present'].add(stage_name)
            if pos >= len(ts):
                unmatched_positions += 1

        event_stage_coverage[eid]['total_chains'] += 1

num_events_with_chains = len(chains_per_event)
total_stages = sum(stage_counts.values())

print(f'Total chains: {total_chains}')
print(f'Events with chains: {num_events_with_chains}')
print(f'Chains per event (avg): {total_chains/num_events_with_chains:.1f}')
print(f'Avg stages per chain: {total_stages/total_chains:.1f}')
print(f'Unique stage types observed: {len(stage_counts)}')
print(f'Chain positions with no matching temporal_stage: {unmatched_positions}')
print()
print('Stage distribution (across all chains):')
for stage, count in stage_counts.most_common():
    pct = count / total_chains * 100
    print(f'  {stage:>15s}: {count:4d} ({pct:5.1f}% of {total_chains} chains)')

print()
print('Stage counts per position:')
for pos in sorted(stage_per_position.keys()):
    pos_data = stage_per_position[pos]
    items = ', '.join(f'{k}: {v}' for k, v in pos_data.most_common())
    print(f'  Position {pos}: {items}')

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Events:       {len(event_ids)} (6 domains, all concrete_event)")
print(f"Gold tuples:  {total_tuples} across {num_events} events ({total_tuples/num_events:.1f}/event)")
print(f"Gold chains:  {total_chains} across {num_events_with_chains} events ({total_chains/num_events_with_chains:.1f}/event)")
print(f"Evidence:     {total} items across {len(events_with_evidence)} events ({total/len(events_with_evidence):.1f}/event), publish_time all null")
print(f"Sources:      {', '.join(f'{s}: {c}' for s,c in source_types.most_common())}")
