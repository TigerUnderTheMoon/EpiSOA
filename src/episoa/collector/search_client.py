"""Search API client for C-FSM evidence collection."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any

import httpx


PLACEHOLDER_PREFIX = "your-"
RETRYABLE_ERROR_HINTS = ("ssl", "handshake", "timeout", "connection")


@dataclass(frozen=True)
class SearchConfig:
    provider: str
    api_key: str | None
    api_key_source: str
    base_url: str | None
    base_url_source: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)


class SearchClient:
    """Small HTTP JSON search client with normalized result fields."""

    def __init__(self, config: SearchConfig):
        if config.provider != "custom":
            raise ValueError(f"unsupported search.provider: {config.provider}")
        self.config = config

    def search(
        self,
        *,
        query: str,
        max_results: int,
        source_type: str | None = None,
        time_window: str | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = self.search_with_debug(
            query=query,
            max_results=max_results,
            source_type=source_type,
            time_window=time_window,
        )
        return result["results"]

    def search_with_debug(
        self,
        *,
        query: str,
        max_results: int,
        source_type: str | None = None,
        time_window: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.config.configured:
            return _debug_result(query, source_type, [], "search API is not configured", "RuntimeError")

        payload = {
            "query": query,
            "max_results": max_results,
            "source_type": source_type,
            "time_window": time_window,
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        timeout = self.config.timeout_seconds or 20
        attempts = 0
        attempt_rows: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
                for attempt_index in range(self.config.max_retries + 1):
                    attempts = attempt_index + 1
                    started_at = time.perf_counter()
                    try:
                        response = client.post(str(self.config.base_url), json=payload, headers=headers, timeout=timeout)
                        if response.status_code in {404, 405}:
                            response = client.get(str(self.config.base_url), params=payload, headers=headers, timeout=timeout)
                        response.raise_for_status()
                        results = normalize_search_response(response.json())[:max_results]
                        attempt_rows.append(
                            _attempt_row(attempts, True, None, None, time.perf_counter() - started_at)
                        )
                        return _debug_result(
                            query,
                            source_type,
                            results,
                            None,
                            None,
                            retry_count=attempts - 1,
                            provider_attempts=attempt_rows,
                        )
                    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.TransportError, ConnectionError) as exc:
                        last_error = exc
                        attempt_rows.append(
                            _attempt_row(attempts, False, type(exc).__name__, str(exc), time.perf_counter() - started_at)
                        )
                        if attempt_index < self.config.max_retries and self.config.retry_backoff_seconds > 0:
                            time.sleep(self.config.retry_backoff_seconds * (2**attempt_index))
                    except (httpx.HTTPError, ValueError) as exc:
                        last_error = exc
                        attempt_rows.append(
                            _attempt_row(attempts, False, type(exc).__name__, str(exc), time.perf_counter() - started_at)
                        )
                        break
                    except Exception as exc:  # Defensive: one bad provider response must not stop a collection run.
                        last_error = exc
                        attempt_rows.append(
                            _attempt_row(attempts, False, type(exc).__name__, str(exc), time.perf_counter() - started_at)
                        )
                        if not _looks_retryable(exc) or attempt_index >= self.config.max_retries:
                            break
                        if self.config.retry_backoff_seconds > 0:
                            time.sleep(self.config.retry_backoff_seconds * (2**attempt_index))
        except Exception as exc:
            last_error = exc
            if not attempt_rows:
                attempt_rows.append(_attempt_row(1, False, type(exc).__name__, str(exc), 0.0))
        error_type = type(last_error).__name__ if last_error else "UnknownError"
        return _debug_result(
            query,
            source_type,
            [],
            str(last_error),
            error_type,
            retry_count=max(0, attempts - 1),
            provider_attempts=attempt_rows,
        )


def _debug_result(
    query: str,
    source_type: str | None,
    results: list[dict[str, Any]],
    error: str | None,
    error_type: str | None,
    retry_count: int = 0,
    provider_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "query": query,
        "source_type": source_type,
        "results": results,
        "result_count": len(results),
        "ok": error is None,
        "error": error,
        "error_type": error_type,
        "timeout": error_type == "TimeoutException",
        "retry_count": retry_count,
        "final_status": "success" if error is None else "failed",
        "provider_attempts": list(provider_attempts or []),
    }


def _attempt_row(
    attempt: int,
    ok: bool,
    error_type: str | None,
    error: str | None,
    duration_seconds: float,
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "ok": ok,
        "error_type": error_type,
        "error": error,
        "duration_seconds": round(duration_seconds, 4),
        "final_status": "success" if ok else "failed",
    }


def _looks_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(hint in text for hint in RETRYABLE_ERROR_HINTS)


def load_search_config(raw: dict[str, Any]) -> SearchConfig:
    api_key, api_key_source = _resolve_config_value(raw, "api_key", "api_key_env")
    base_url, base_url_source = _resolve_config_value(raw, "base_url", "base_url_env")
    return SearchConfig(
        provider=str(raw.get("provider", "custom")),
        api_key=api_key,
        api_key_source=api_key_source,
        base_url=base_url,
        base_url_source=base_url_source,
        timeout_seconds=float(raw.get("timeout_seconds", 20)),
        max_retries=int(raw.get("max_retries", 2)),
        retry_backoff_seconds=float(raw.get("retry_backoff_seconds", 0)),
    )


def normalize_search_response(payload: Any) -> list[dict[str, Any]]:
    records = _extract_records(payload)
    return [_normalize_record(record) for record in records if isinstance(record, dict)]


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_records(value)
            if nested and nested != [value]:
                return nested
    web_pages = payload.get("webPages")
    if isinstance(web_pages, dict) and isinstance(web_pages.get("value"), list):
        return [item for item in web_pages["value"] if isinstance(item, dict)]
    return [payload]


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    title = _first(record, "title", "name", "headline")
    url = _first(record, "link", "url")
    snippet = _first(record, "snippet", "summary", "description")
    text = _first(record, "content", "text", "body") or snippet or title or ""
    publish_time = _first(record, "date", "published_at", "publish_time")
    platform = _first(record, "source", "site", "platform") or _host_from_url(url) or "unknown"
    source = _first(record, "source_type", "type", "category") or platform
    return {
        "title": title or "",
        "url": url,
        "snippet": snippet,
        "text": text,
        "platform": platform,
        "publish_time": publish_time,
        "source": source,
    }


def _first(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return httpx.URL(url).host
    except Exception:
        return None


def _resolve_config_value(raw: dict[str, Any], direct_key: str, env_key: str) -> tuple[str | None, str]:
    direct = raw.get(direct_key)
    if isinstance(direct, str) and direct.strip() and not _is_placeholder(direct):
        return direct.strip(), "yaml"
    env_name = raw.get(env_key)
    if isinstance(env_name, str) and env_name.strip():
        value = os.getenv(env_name.strip())
        if value and not _is_placeholder(value):
            return value, f"env:{env_name.strip()}"
    return None, "missing"


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(PLACEHOLDER_PREFIX) or "your-" in lowered or "your_" in lowered
