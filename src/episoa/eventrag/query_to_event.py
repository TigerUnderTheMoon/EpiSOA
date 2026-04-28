"""Query-to-event parsing for EventRAG retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryEvent:
    """Parsed event-oriented query representation."""

    query: str
    target_event: str
    keywords: set[str]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("-", " ").split() if token.strip()}


def parse_query_to_event(query: str) -> QueryEvent:
    """Parse a natural-language query into a lightweight event query."""
    query = query.strip()
    if not query:
        raise ValueError("query must not be blank")

    return QueryEvent(query=query, target_event=query, keywords=_tokens(query))
