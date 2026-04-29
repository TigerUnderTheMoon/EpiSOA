"""Minimal search client abstraction for configured public search results."""

from __future__ import annotations

from typing import Any


class SearchClient:
    """Return locally supplied search results without calling external APIs."""

    def __init__(self, results_by_query: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.results_by_query = results_by_query or {}

    def search(self, query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
        return list(self.results_by_query.get(query, []))[:top_k]


__all__ = ["SearchClient"]
