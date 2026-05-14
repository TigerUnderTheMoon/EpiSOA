"""Generate case studies for selected events with chain visualization."""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_case_study(
    event_id: str,
    events: list[dict],
    evidence: list[dict],
    gold_tuples: list[dict],
    gold_chains: list[dict],
    tuple_preds: list[dict],
    chain_preds: list[dict],
) -> str:
    event = next((e for e in events if e.get("event_id") == event_id), {})
    ev_evidence = [e for e in evidence if e.get("event_id") == event_id]
    ev_gold_tuples = [t for t in gold_tuples if t.get("event_id") == event_id]
    ev_gold_chains = [c for c in gold_chains if c.get("event_id") == event_id]

    # Find prediction for this event
    tp = next((p for p in tuple_preds if p.get("event_id") == event_id), None)
    cp = next((p for p in chain_preds if p.get("event_id") == event_id), None)

    pred_tuples = tp["prediction"].get("tuples", []) if tp else []
    pred_chains = cp["prediction"].get("chains", []) if cp else []

    lines = []
    lines.append("=" * 70)
    lines.append(f"CASE STUDY: {event_id}")
    lines.append("=" * 70)
    lines.append(f"")
    lines.append(f"Event: {event.get('event_name', 'N/A')}")
    lines.append(f"Domain: {event.get('domain', 'N/A')}")
    lines.append(f"Location: {event.get('location', {}).get('city', '')}, {event.get('location', {}).get('province', '')}")
    lines.append(f"Time: {event.get('time_window', {}).get('start', '')} ~ {event.get('time_window', {}).get('end', '')}")
    lines.append(f"Trigger: {event.get('trigger', '')}")
    lines.append(f"Evidence: {len(ev_evidence)} items | Gold tuples: {len(ev_gold_tuples)} | Gold chains: {len(ev_gold_chains)}")

    # Stakeholders in gold
    lines.append(f"\n--- GOLD STAKEHOLDER OPINIONS ---")
    for t in ev_gold_tuples:
        lines.append(f"  [{t.get('stakeholder', '?')}] {t.get('opinion', '?')}")
        lines.append(f"    Sentiment: {t.get('sentiment', '?')}  Evidence: {t.get('evidence_ids', [])[:4]}")

    # Event chains (gold)
    lines.append(f"\n--- GOLD EVENT CHAINS ---")
    for i, chain in enumerate(ev_gold_chains):
        lines.append(f"  Chain {i+1} ({chain.get('chain_id', '?')}):")
        for j, stage in enumerate(chain.get("event_chain", [])):
            lines.append(f"    Stage {j+1}: {stage}")
        lines.append(f"    Evidence: {chain.get('evidence_ids', [])[:6]}")

    # Predicted chains
    lines.append(f"\n--- PREDICTED EVENT CHAINS ---")
    if pred_chains:
        for i, chain in enumerate(pred_chains):
            lines.append(f"  Chain {i+1}:")
            for j, stage in enumerate(chain.get("event_chain", [])):
                lines.append(f"    Stage {j+1}: {stage}")
            lines.append(f"    Evidence: {chain.get('evidence_ids', [])[:6]}")
    else:
        lines.append("  (no chains predicted)")

    # Chain evidence overlap analysis
    lines.append(f"\n--- CHAIN EVIDENCE OVERLAP ---")
    gold_ev = set()
    for gc in ev_gold_chains:
        for eid in gc.get("evidence_ids", []):
            gold_ev.add(eid)
    pred_ev = set()
    for pc in pred_chains:
        for eid in pc.get("evidence_ids", []):
            pred_ev.add(eid)

    overlap = gold_ev & pred_ev
    gold_only = gold_ev - pred_ev
    pred_only = pred_ev - gold_ev

    lines.append(f"  Gold evidence: {len(gold_ev)}")
    lines.append(f"  Pred evidence: {len(pred_ev)}")
    lines.append(f"  Overlap: {len(overlap)} ({len(overlap)/max(len(gold_ev),1)*100:.0f}%)")
    if gold_only:
        lines.append(f"  Gold-only evidence IDs: {sorted(gold_only)[:8]}")
    if pred_only:
        lines.append(f"  Pred-only evidence IDs: {sorted(pred_only)[:8]}")

    # Source diversity
    lines.append(f"\n--- EVIDENCE SOURCE DIVERSITY ---")
    source_counts = defaultdict(int)
    for ev in ev_evidence:
        source_counts[ev.get("source_type", "?")] += 1
    for st, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {st}: {count}")

    # Predicted tuples (LLM judge match analysis)
    lines.append(f"\n--- PREDICTED TUPLES vs GOLD ---")
    if pred_tuples:
        for pt in pred_tuples:
            lines.append(f"  [PRED: {pt.get('stakeholder', '?')}] {pt.get('opinion', '?')}")
            lines.append(f"    Sentiment: {pt.get('sentiment', '?')}  Evidence: {pt.get('evidence_ids', [])[:4]}")
    else:
        lines.append("  (no tuples predicted)")

    lines.append(f"\n--- DIAGNOSTICS ---")
    lines.append(f"  Pred tuples: {len(pred_tuples)}  Gold tuples: {len(ev_gold_tuples)}")
    lines.append(f"  Pred chains: {len(pred_chains)}  Gold chains: {len(ev_gold_chains)}")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", nargs="+", default=["E001", "E003", "E018"],
                        help="Event IDs for case studies")
    parser.add_argument("--output", default="outputs/paper_tables/case_studies.md")
    parser.add_argument("--run-dir", default="outputs/benchmark_runs/pubevent-soa-lite-paper_deepseek-v4-flash")
    args = parser.parse_args()

    events = load_jsonl("data/pubevent_soa_lite/events.jsonl")
    evidence = load_jsonl("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
    gold_tuples = load_jsonl("data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl")
    gold_chains = load_jsonl("data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl")
    tuple_preds = load_jsonl(Path(args.run_dir) / "tuple_identification_predictions.jsonl")
    chain_preds = load_jsonl(Path(args.run_dir) / "chain_construction_predictions.jsonl")

    output_parts = []
    for eid in args.events:
        case = render_case_study(eid, events, evidence, gold_tuples, gold_chains, tuple_preds, chain_preds)
        output_parts.append(case)
        output_parts.append("")

    full_output = "\n".join(output_parts)
    Path(args.output).write_text(full_output, encoding="utf-8")
    print(full_output)
    print(f"\nSaved to {args.output}")

if __name__ == "__main__":
    main()
