"""Lightweight public web fetching for the C-FSM collector."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_USER_AGENT = "EpiSOA research crawler (+public evidence collection; contact: local researcher)"
MAX_PAGE_TEXT_CHARS = 12000


@dataclass(frozen=True)
class PublicPage:
    """A fetched public page normalized into collector page fields."""

    evidence_id: str
    url: str
    platform: str
    source: str
    title: str
    text: str
    timestamp: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "url": self.url,
            "platform": self.platform,
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "crawl_method": "public_http_fetch",
        }


class PublicPageFetcher:
    """Fetch public HTTP(S) pages without authentication or access bypass."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        user_agent: str = DEFAULT_USER_AGENT,
        max_text_chars: int = MAX_PAGE_TEXT_CHARS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.max_text_chars = max_text_chars

    def fetch(self, url: str) -> PublicPage:
        normalized_url = validate_public_url(url)
        response = httpx.get(
            normalized_url,
            follow_redirects=True,
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type and content_type:
            raise ValueError(f"unsupported content type: {content_type}")
        return page_from_content(
            normalized_url,
            response.text,
            max_text_chars=self.max_text_chars,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )


def validate_public_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"only public http(s) URLs can be fetched: {url!r}")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")
    return parsed.geturl()


def page_from_content(
    url: str,
    content: str,
    *,
    max_text_chars: int = MAX_PAGE_TEXT_CHARS,
    fetched_at: str | None = None,
) -> PublicPage:
    parsed = urlparse(url)
    title, text, metadata = extract_page_text(content)
    platform = parsed.netloc.lower()
    source = classify_source(platform, text)
    evidence_id = stable_evidence_id(url)
    return PublicPage(
        evidence_id=evidence_id,
        url=url,
        platform=platform,
        source=source,
        title=title,
        text=text[:max_text_chars],
        timestamp=metadata.get("published_time") or fetched_at or datetime.now(timezone.utc).isoformat(),
        metadata={
            **metadata,
            "source_family": source,
            "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        },
    )


def extract_page_text(content: str) -> tuple[str, str, dict[str, Any]]:
    parser = ReadableHTMLParser()
    parser.feed(content)
    title = compact_text(unescape(parser.title))
    text = compact_text(unescape(" ".join(parser.text_parts)))
    if not text:
        text = compact_text(strip_tags(content))
    return title, text, parser.metadata


def classify_source(host: str, text: str) -> str:
    lowered = f"{host} {text[:1000]}".lower()
    if any(token in lowered for token in ("forum", "thread", "bbs", "reddit", "comment", "讨论")):
        return "forum"
    if any(token in host.lower() for token in ("news", "press", "daily", "times", "post", "日报", "新闻")):
        return "news"
    if any(token in lowered for token in ("gov", "government", "official", "authority", "公告", "政府")):
        return "official_response"
    if any(token in lowered for token in ("news", "press", "daily", "times", "post", "日报", "新闻")):
        return "news"
    return "public_web"


def stable_evidence_id(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"web-{digest}"


def compact_text(value: str) -> str:
    return " ".join(value.split())


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


class ReadableHTMLParser(HTMLParser):
    """Conservative text extractor that skips scripts, styles, and navigation noise."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text_parts: list[str] = []
        self.metadata: dict[str, Any] = {}
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            self._capture_meta(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += f" {text}"
            return
        if self._skip_depth:
            return
        self.text_parts.append(text)

    def _capture_meta(self, attrs: dict[str, str]) -> None:
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content", "").strip()
        if not name or not content:
            return
        if name in {"description", "og:description", "twitter:description"}:
            self.metadata.setdefault("description", content)
        elif name in {"article:published_time", "date", "pubdate", "publishdate"}:
            self.metadata.setdefault("published_time", content)
        elif name in {"author", "article:author"}:
            self.metadata.setdefault("author_name", content)
