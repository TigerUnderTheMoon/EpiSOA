"""Error analysis for EpiSOA benchmark predictions.

Categorizes failure modes across all 3 benchmark tasks.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def analyze_tuple_identification(run_dir: str) -> dict:
    """Analyze tuple identification errors."""
    preds = _read_jsonl(Path(run_dir) / "tuple_identification_predictions.jsonl")

    summary = {
        "total_events": len(preds),
        "events_with_predictions": 0,
        "events_with_no_predictions": [],
        "total_gold_tuples": 0,
        "total_pred_tuples": 0,
        "exact_matches": 0,
        "soft_candidates": 0,
        "missing_stakeholder_types": Counter(),
        "sentiment_errors": [],
        "per_event": [],
    }

    for p in preds:
        gold_tuples = p["output"]["gold_tuples"]
        pred_data = p["prediction"]
        pred_tuples = pred_data.get("tuples", [])
        event_id = p["event_id"]

        summary["total_gold_tuples"] += len(gold_tuples)
        summary["total_pred_tuples"] += len(pred_tuples)

        if pred_tuples:
            summary["events_with_predictions"] += 1
        else:
            summary["events_with_no_predictions"].append(event_id)

        # Per-event analysis
        event_analysis = {
            "event_id": event_id,
            "gold_count": len(gold_tuples),
            "pred_count": len(pred_tuples),
            "exact_matches": 0,
            "sentiment_matches": 0,
            "pred_stakeholders": [pt.get("stakeholder", "") for pt in pred_tuples],
            "gold_stakeholders": [gt.get("stakeholder", "") for gt in gold_tuples],
        }

        for gt in gold_tuples:
            for pt in pred_tuples:
                if (gt.get("stakeholder", "").strip() == pt.get("stakeholder", "").strip()
                        and gt.get("opinion", "").strip() == pt.get("opinion", "").strip()):
                    event_analysis["exact_matches"] += 1
                    summary["exact_matches"] += 1
                    if gt.get("sentiment") == pt.get("sentiment"):
                        event_analysis["sentiment_matches"] += 1

        summary["per_event"].append(event_analysis)

    # Aggregate sentiment errors
    sentiment_dist = Counter()
    gold_sentiment_dist = Counter()
    for p in preds:
        for gt in p["output"]["gold_tuples"]:
            gold_sentiment_dist[gt.get("sentiment", "?")] += 1
        for pt in p["prediction"].get("tuples", []):
            sentiment_dist[pt.get("sentiment", "?")] += 1

    summary["gold_sentiment_dist"] = dict(gold_sentiment_dist)
    summary["pred_sentiment_dist"] = dict(sentiment_dist)

    # Stakeholder coverage
    gold_stakeholders = set()
    pred_stakeholders = set()
    for p in preds:
        for gt in p["output"]["gold_tuples"]:
            gold_stakeholders.add(gt.get("stakeholder", ""))
        for pt in p["prediction"].get("tuples", []):
            pred_stakeholders.add(pt.get("stakeholder", ""))

    summary["unique_gold_stakeholders"] = len(gold_stakeholders)
    summary["unique_pred_stakeholders"] = len(pred_stakeholders)
    summary["stakeholder_recall"] = len(gold_stakeholders & pred_stakeholders) / len(gold_stakeholders) if gold_stakeholders else 0

    return summary


def analyze_evidence_support(run_dir: str) -> dict:
    """Analyze evidence support classification errors."""
    preds = _read_jsonl(Path(run_dir) / "evidence_support_predictions.jsonl")

    total = len(preds)
    correct = 0
    confusion = defaultdict(Counter)
    error_cases = []

    for p in preds:
        gold = p["gold_label"]
        pred_label = p["prediction"].get("support_label", "not_enough_info")
        sample_type = p.get("sample_type", "unknown")

        if gold == pred_label:
            correct += 1
        else:
            error_cases.append({
                "task_id": p["task_id"],
                "event_id": p["event_id"],
                "gold": gold,
                "pred": pred_label,
                "sample_type": sample_type,
            })

        confusion[gold][pred_label] += 1

    # Categorize errors
    error_by_type = defaultdict(list)
    for err in error_cases:
        key = f"{err['gold']}→{err['pred']}"
        error_by_type[key].append(err["event_id"])

    error_summary = {}
    for key, events in sorted(error_by_type.items(), key=lambda x: -len(x[1])):
        error_summary[key] = {
            "count": len(events),
            "pct": f"{len(events)/total*100:.1f}%",
            "sample_events": events[:3],
        }

    # Per-class breakdown
    per_class = {}
    for label in ["supported", "partially_supported", "not_enough_info"]:
        gold_total = sum(confusion[label].values())
        pred_total = sum(confusion[l][label] for l in confusion)
        tp = confusion[label][label]
        per_class[label] = {
            "gold_count": gold_total,
            "pred_count": pred_total,
            "tp": tp,
            "precision": f"{tp/pred_total*100:.1f}%" if pred_total else "N/A",
            "recall": f"{tp/gold_total*100:.1f}%" if gold_total else "N/A",
        }

    # Positive vs negative breakdown
    positive_errors = [e for e in error_cases if e["sample_type"] == "positive"]
    negative_errors = [e for e in error_cases if "negative" in e.get("sample_type", "")]

    return {
        "total": total,
        "accuracy": f"{correct/total*100:.1f}%",
        "correct": correct,
        "errors": len(error_cases),
        "positive_errors": len(positive_errors),
        "negative_errors": len(negative_errors),
        "error_breakdown": error_summary,
        "per_class": per_class,
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def analyze_chain_construction(run_dir: str) -> dict:
    """Analyze chain construction errors."""
    preds = _read_jsonl(Path(run_dir) / "chain_construction_predictions.jsonl")

    summary = {
        "total_events": len(preds),
        "events_with_match": 0,
        "events_without_match": [],
        "events_with_empty_pred": [],
        "gold_chain_distribution": Counter(),
        "pred_chain_distribution": Counter(),
        "per_event_overlap": [],
    }

    for p in preds:
        event_id = p["event_id"]
        gold_chains = p["output"]["gold_chains"]
        pred_data = p["prediction"]
        pred_chains = pred_data.get("chains", [])

        summary["gold_chain_distribution"][len(gold_chains)] += 1
        summary["pred_chain_distribution"][len(pred_chains)] += 1

        if not pred_chains:
            summary["events_with_empty_pred"].append(event_id)

        gold_ev_ids = set()
        for gc in gold_chains:
            for eid in gc.get("evidence_ids", []):
                gold_ev_ids.add(eid)

        pred_ev_ids = set()
        for pc in pred_chains:
            for eid in pc.get("evidence_ids", []):
                pred_ev_ids.add(eid)

        overlap = gold_ev_ids & pred_ev_ids
        summary["per_event_overlap"].append({
            "event_id": event_id,
            "gold_evidence_count": len(gold_ev_ids),
            "pred_evidence_count": len(pred_ev_ids),
            "overlap_count": len(overlap),
            "overlap_pct": f"{len(overlap)/len(gold_ev_ids)*100:.1f}%" if gold_ev_ids else "0%",
            "gold_stages": [len(gc.get("event_chain", [])) for gc in gold_chains],
            "pred_stages": [len(pc.get("event_chain", [])) for pc in pred_chains],
        })

        if overlap:
            summary["events_with_match"] += 1
        else:
            summary["events_without_match"].append(event_id)

    # Sort by overlap
    summary["per_event_overlap"].sort(key=lambda x: float(x["overlap_pct"].replace("%", "")))

    return summary


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="outputs/benchmark_runs/pubevent-soa-lite-paper_deepseek-v4-flash")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print("=" * 60)
    print("EPISOA ERROR ANALYSIS")
    print("=" * 60)

    # Tuple Identification
    print("\n--- TUPLE IDENTIFICATION ---")
    ti = analyze_tuple_identification(args.run_dir)
    print(f"Events: {ti['total_events']}")
    print(f"Events with predictions: {ti['events_with_predictions']}/{ti['total_events']}")
    print(f"Events with NO predictions: {ti['events_with_no_predictions']}")
    print(f"Gold tuples: {ti['total_gold_tuples']}, Pred tuples: {ti['total_pred_tuples']}")
    print(f"Exact matches: {ti['exact_matches']}")
    print(f"Unique gold stakeholders: {ti['unique_gold_stakeholders']}, pred: {ti['unique_pred_stakeholders']}")
    print(f"Stakeholder set recall: {ti['stakeholder_recall']:.2%}")
    print(f"Gold sentiment: {ti['gold_sentiment_dist']}")
    print(f"Pred sentiment: {ti['pred_sentiment_dist']}")

    # Top per-event stats
    print("\nPer-event summary (first 5):")
    for ev in ti["per_event"][:5]:
        print(f"  {ev['event_id']}: gold={ev['gold_count']} pred={ev['pred_count']} "
              f"exact_matches={ev['exact_matches']}")

    # Evidence Support
    print("\n--- EVIDENCE SUPPORT CLASSIFICATION ---")
    esc = analyze_evidence_support(args.run_dir)
    print(f"Total: {esc['total']}, Accuracy: {esc['accuracy']}")
    print(f"Positive errors: {esc['positive_errors']}, Negative errors: {esc['negative_errors']}")
    print(f"\nPer-class:")
    for label, stats in esc["per_class"].items():
        print(f"  {label}: gold={stats['gold_count']} pred={stats['pred_count']} "
              f"tp={stats['tp']} prec={stats['precision']} rec={stats['recall']}")
    print(f"\nTop error patterns:")
    for pattern, info in list(esc["error_breakdown"].items())[:5]:
        print(f"  {pattern}: {info['count']} ({info['pct']}) — {info['sample_events']}")

    # Chain Construction
    print("\n--- CHAIN CONSTRUCTION ---")
    cc = analyze_chain_construction(args.run_dir)
    print(f"Events: {cc['total_events']}")
    print(f"Events with evidence match: {cc['events_with_match']}")
    print(f"Events without match: {cc['events_without_match']}")
    print(f"Events with empty predictions: {cc['events_with_empty_pred']}")
    print(f"Gold chain count distribution: {dict(cc['gold_chain_distribution'])}")
    print(f"Pred chain count distribution: {dict(cc['pred_chain_distribution'])}")

    # Events with lowest overlap
    print("\nLowest overlap events:")
    for ev in cc["per_event_overlap"][:5]:
        print(f"  {ev['event_id']}: gold_ev={ev['gold_evidence_count']} "
              f"pred_ev={ev['pred_evidence_count']} overlap={ev['overlap_count']} ({ev['overlap_pct']})")
    print("\nHighest overlap events:")
    for ev in cc["per_event_overlap"][-5:]:
        print(f"  {ev['event_id']}: gold_ev={ev['gold_evidence_count']} "
              f"pred_ev={ev['pred_evidence_count']} overlap={ev['overlap_count']} ({ev['overlap_pct']})")

    if args.output:
        output = {
            "tuple_identification": ti,
            "evidence_support": esc,
            "chain_construction": cc,
        }
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nSaved to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
