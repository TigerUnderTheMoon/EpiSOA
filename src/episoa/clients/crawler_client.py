"""Crawler client for public HTTP(S) evidence pages."""

from episoa.collector.web_fetch import PublicPage, PublicPageFetcher


class CrawlerClient(PublicPageFetcher):
    """Thin spec-facing wrapper around the public page fetcher."""


__all__ = ["CrawlerClient", "PublicPage", "PublicPageFetcher"]
