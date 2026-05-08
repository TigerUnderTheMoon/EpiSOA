"""Retrieval evaluation."""

from __future__ import annotations


def evaluate_retrieval(gold_chains: list[dict], predicted_paths: list[dict]) -> dict[str, float]:
    if not gold_chains:
        return {"Path-Recall@5": 0.0}
    predicted = {tuple(item.get("event_chain", [])) for item in predicted_paths}
    gold = {tuple(item.get("event_chain") or item.get("chain_nodes") or []) for item in gold_chains}
    return {"Path-Recall@5": len(gold & predicted) / len(gold) if gold else 0.0}
