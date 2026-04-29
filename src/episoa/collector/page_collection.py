"""S3 search and page collection for C-FSM evidence collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from episoa.collector.common import (
    MAX_EVIDENCE_PER_EVENT,
    MAX_PAGES_PER_QUERY,
    MAX_QUERIES_PER_EVENT,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    SUPPORTED_SEMIREAL_SOURCES,
    bounded_int,
    collection_mode,
    visit,
)
from episoa.collector.web_fetch import PublicPageFetcher


def search_and_page_collection(state: dict[str, Any]) -> dict[str, Any]:
    """Collect bounded page records from search results or configured seeds."""
    if collection_mode(state) == "semireal_search":
        max_pages = bounded_int(state, "max_pages_per_query", MAX_PAGES_PER_QUERY, MAX_PAGES_PER_QUERY)
        max_evidence = bounded_int(state, "max_evidence_per_event", MAX_EVIDENCE_PER_EVENT, MAX_EVIDENCE_PER_EVENT)
        selected_sources = set(state.get("selected_sources", SUPPORTED_SEMIREAL_SOURCES))
        search_results = state.get("search_results", {})
        fetcher = _page_fetcher(state)
        pages: list[dict[str, Any]] = []
        fetch_errors: list[str] = []
        seen_urls: set[str] = set()

        for query in state.get("query_plan", [])[:MAX_QUERIES_PER_EVENT]:
            query_pages = list(search_results.get(query, []))[:max_pages]
            if state.get("fetch_search_results"):
                query_pages = [
                    _fetch_page_if_needed(page, query, fetcher, fetch_errors)
                    for page in query_pages
                ]
            if not query_pages and state.get("seed_urls"):
                query_pages = [
                    _seed_to_page(seed, query, fetcher=fetcher, fetch_errors=fetch_errors, should_fetch=bool(state.get("fetch_seed_urls")))
                    for seed in state.get("seed_urls", [])
                ][:max_pages]
            for page in query_pages:
                if not page:
                    continue
                source = str(page.get("source") or page.get("source_type") or "public_web")
                if source not in selected_sources:
                    continue
                url = str(page.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                pages.append({**page, "query": query, "source": source})
                if len(pages) >= max_evidence:
                    break
            if len(pages) >= max_evidence:
                break

        return {
            "visited_states": visit(state, "search_and_page_collection"),
            "pages": pages,
            "fetch_errors": fetch_errors,
        }

    pages = [
        {
            "url": "https://example.com/news/mock-event",
            "title": "Mock event coverage",
            "source": "news",
        },
        {
            "url": "https://example.com/social/mock-event",
            "title": "Mock public reactions",
            "source": "social_media",
        },
    ]
    return {
        "visited_states": visit(state, "search_and_page_collection"),
        "pages": pages,
    }


def _seed_to_page(
    seed: str | dict[str, Any],
    query: str,
    *,
    fetcher: Any,
    fetch_errors: list[str],
    should_fetch: bool,
) -> dict[str, Any] | None:
    if isinstance(seed, dict):
        return _fetch_page_if_needed({**seed, "query": query}, query, fetcher, fetch_errors) if should_fetch else {**seed, "query": query}
    if should_fetch:
        return _fetch_url(str(seed), query, fetcher, fetch_errors)
    return {
        "url": str(seed),
        "title": str(seed),
        "text": f"Public seed page related to {query}",
        "platform": "public_web",
        "source": "public_web",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"stakeholder": "unknown", "sentiment": "unknown"},
    }


def _fetch_page_if_needed(
    page: dict[str, Any],
    query: str,
    fetcher: Any,
    fetch_errors: list[str],
) -> dict[str, Any] | None:
    if page.get("text") or page.get("snippet"):
        return page
    url = str(page.get("url") or "").strip()
    if not url:
        return page
    fetched = _fetch_url(url, query, fetcher, fetch_errors)
    return {**fetched, **{key: value for key, value in page.items() if value not in (None, "")}} if fetched else page


def _fetch_url(url: str, query: str, fetcher: Any, fetch_errors: list[str]) -> dict[str, Any] | None:
    try:
        if callable(fetcher):
            page = fetcher(url)
        else:
            page = fetcher.fetch(url)
        page_dict = page.as_dict() if hasattr(page, "as_dict") else dict(page)
        return {**page_dict, "query": query}
    except Exception as exc:  # noqa: BLE001 - collection records bad URLs and continues.
        fetch_errors.append(f"{url}: {exc}")
        return None


def _page_fetcher(state: dict[str, Any]) -> Any:
    if state.get("page_fetcher") is not None:
        return state["page_fetcher"]
    return PublicPageFetcher(
        timeout_seconds=float(state.get("http_timeout_seconds", DEFAULT_HTTP_TIMEOUT_SECONDS)),
        user_agent=str(state.get("user_agent", DEFAULT_USER_AGENT)),
    )
