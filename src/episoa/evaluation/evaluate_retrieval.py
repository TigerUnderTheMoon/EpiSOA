"""Retrieval evaluation."""

from __future__ import annotations


def evaluate_retrieval(gold_chains: list[dict], predicted_paths: list[dict]) -> dict[str, float]:
    """Evaluate retrieval quality via evidence-level overlap with gold chains.

    Retrieval output: [{"event_id": ..., "stages": [{"evidence": [...]}, ...]}, ...]
    Gold chains: [{"event_id": ..., "evidence_ids": [...]}, ...]

    Computes evidence-level recall and precision against gold chain evidence sets.
    """
    if not gold_chains or not predicted_paths:
        return {"evidence_recall@5": 0.0, "evidence_precision@5": 0.0, "evidence_f1@5": 0.0}

    # Build retrieved evidence sets per event
    retrieved_evidence: dict[str, set[str]] = {}
    for path in predicted_paths:
        event_id = str(path.get("event_id", ""))
        ev_ids = set()
        for stage in path.get("stages", []):
            for ev in stage.get("evidence", []):
                eid = ev.get("evidence_id", "")
                if eid:
                    ev_ids.add(eid)
        retrieved_evidence[event_id] = ev_ids

    # Build gold evidence sets per event
    gold_evidence: dict[str, set[str]] = {}
    for gc in gold_chains:
        event_id = str(gc.get("event_id", ""))
        ev_ids = set()
        for eid in gc.get("evidence_ids", []):
            if eid:
                ev_ids.add(eid)
        if ev_ids:
            gold_evidence[event_id] = ev_ids

    # Compute overlap
    total_gold = 0
    total_retrieved = 0
    total_overlap = 0

    for event_id, gold_set in gold_evidence.items():
        ret_set = retrieved_evidence.get(event_id, set())
        total_gold += len(gold_set)
        total_retrieved += len(ret_set)
        total_overlap += len(gold_set & ret_set)

    recall = total_overlap / total_gold if total_gold > 0 else 0.0
    precision = total_overlap / total_retrieved if total_retrieved > 0 else 0.0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0

    return {
        "evidence_recall@5": round(recall, 4),
        "evidence_precision@5": round(precision, 4),
        "evidence_f1@5": round(f1, 4),
    }
