"""Deterministic reranker used by the reproducible workflow."""

from __future__ import annotations


def rerank(items: list[dict], top_k: int) -> list[dict]:
    return items[:top_k]
