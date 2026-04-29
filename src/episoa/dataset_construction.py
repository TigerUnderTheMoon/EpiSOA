"""Dataset construction utilities for PubEvent-SOA urban renewal data."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from episoa.preprocess.privacy_filter import PrivacyFilterStats, sanitize_text


URBAN_RENEWAL_TERMS = (
    "urban renewal",
    "city renewal",
    "redevelopment",
    "renovation",
    "旧改",
    "城市更新",
    "征收",
    "拆迁",
    "改造",
)
STAKEHOLDER_HINTS = {
    "residents": ("居民", "业主", "住户", "tenant", "resident"),
    "government": ("政府", "街道", "住建", "城管", "official", "authority"),
    "developer": ("开发商", "建设单位", "企业", "company", "developer"),
    "businesses": ("商户", "店主", "business", "shop"),
}
NEGATIVE_TERMS = ("反对", "质疑", "担心", "不满", "焦虑", "愤怒", "opposed", "concern", "angry")
POSITIVE_TERMS = ("支持", "认可", "赞成", "改善", "期待", "support", "welcome")
MIXED_TERMS = ("但是", "同时", "一方面", "另一方面", "mixed")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    file_path = Path(path)
    if not file_path.exists():
        return records
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            records.append(json.loads(line))
    return records


def write_jsonl(records: list[dict[str, Any]], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def import_raw_posts(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Import CSV or JSONL public-text exports into raw_posts.jsonl."""
    source_path = Path(input_path)
    rows = _read_source_rows(source_path)
    stats = PrivacyFilterStats()
    raw_posts = [normalize_raw_post(row, index=index, stats=stats, provenance=str(source_path)) for index, row in enumerate(rows, start=1)]
    write_jsonl(raw_posts, output_path)
    return {"input_path": str(source_path), "output_path": str(output_path), "num_raw_posts": len(raw_posts), **stats.to_dict()}


def light_crawl_urls(
    urls_path: str | Path,
    output_path: str | Path,
    *,
    fetcher: Callable[[str], str] | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Fetch public URLs into raw_posts.jsonl without bypassing access controls."""
    urls = [line.strip() for line in Path(urls_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = PrivacyFilterStats()
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, url in enumerate(urls, start=1):
        try:
            content = fetcher(url) if fetcher is not None else _http_get_text(url, timeout_seconds)
            title, text = extract_page_text(content)
            records.append(
                normalize_raw_post(
                    {
                        "raw_id": f"url-{index:05d}",
                        "url": url,
                        "platform": _host_from_url(url),
                        "source_type": "news",
                        "title": title,
                        "text": text,
                        "crawl_method": "light_url_fetch",
                    },
                    index=index,
                    stats=stats,
                    provenance=str(urls_path),
                )
            )
        except Exception as exc:  # noqa: BLE001 - batch crawler records failures and continues.
            errors.append(f"{url}: {exc}")
    write_jsonl(records, output_path)
    return {
        "urls_path": str(urls_path),
        "output_path": str(output_path),
        "num_urls": len(urls),
        "num_raw_posts": len(records),
        "errors": errors,
        **stats.to_dict(),
    }


def extract_events(raw_posts_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Extract stable urban-renewal event records from raw posts."""
    raw_posts = load_jsonl(raw_posts_path)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for post in raw_posts:
        seed = str(post.get("event_seed_id") or _event_seed_from_text(str(post.get("text") or post.get("title") or "")))
        grouped.setdefault(seed, []).append(post)

    events: list[dict[str, Any]] = []
    for index, (seed, posts) in enumerate(sorted(grouped.items()), start=1):
        timestamps = sorted(str(post.get("timestamp") or "") for post in posts if post.get("timestamp"))
        target_event = _target_event(seed, posts)
        event_id = _stable_id("evt", seed, index)
        events.append(
            {
                "event_id": event_id,
                "event_seed_id": seed,
                "target_event": target_event,
                "domain": "urban_renewal",
                "time_window": {
                    "start": timestamps[0] if timestamps else "",
                    "end": timestamps[-1] if timestamps else "",
                },
                "event_chain": _event_chain_for_posts(posts, target_event),
                "stakeholder_hints": sorted(_stakeholders_for_posts(posts)),
                "num_raw_posts": len(posts),
            }
        )
    write_jsonl(events, output_path)
    return {"raw_posts_path": str(raw_posts_path), "output_path": str(output_path), "num_events": len(events)}


def generate_silver_tuples(
    raw_posts_path: str | Path,
    events_path: str | Path,
    output_path: str | Path,
    *,
    llm_model: str = "rule_based_silver",
    prompt_version: str = "urban-renewal-v1",
) -> dict[str, Any]:
    """Generate weakly labeled candidate attribution tuples from raw posts."""
    events = {event["event_seed_id"]: event for event in load_jsonl(events_path)}
    silver_rows: list[dict[str, Any]] = []
    for index, post in enumerate(load_jsonl(raw_posts_path), start=1):
        seed = str(post.get("event_seed_id") or _event_seed_from_text(str(post.get("text") or "")))
        event = events.get(seed) or next(iter(events.values()), {})
        text = str(post.get("text") or "")
        evidence_id = str(post.get("raw_id") or f"raw-{index:05d}")
        stakeholder = infer_stakeholder(text)
        sentiment = infer_sentiment(text)
        silver_rows.append(
            {
                "tuple_id": f"silver-{index:05d}",
                "event_id": event.get("event_id", ""),
                "raw_id": evidence_id,
                "stakeholder": stakeholder,
                "opinion": infer_opinion(text, stakeholder),
                "sentiment": sentiment,
                "rationale": infer_rationale(text),
                "event_chain": event.get("event_chain", [event.get("target_event", "")]),
                "evidence_ids": [evidence_id],
                "label_source": "llm_silver",
                "llm_model": llm_model,
                "prompt_version": prompt_version,
                "confidence": confidence_for_silver(text, stakeholder, sentiment),
            }
        )
    write_jsonl(silver_rows, output_path)
    return {"raw_posts_path": str(raw_posts_path), "events_path": str(events_path), "output_path": str(output_path), "num_silver_tuples": len(silver_rows)}


def build_evidence_pairs(raw_posts_path: str | Path, silver_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Join raw posts and silver tuples into annotation-ready evidence pairs."""
    posts = {str(post.get("raw_id")): post for post in load_jsonl(raw_posts_path)}
    pairs: list[dict[str, Any]] = []
    for index, silver in enumerate(load_jsonl(silver_path), start=1):
        raw_id = str((silver.get("evidence_ids") or [silver.get("raw_id")])[0])
        post = posts.get(raw_id, {})
        pairs.append(
            {
                "candidate_id": f"cand-{index:05d}",
                "event_id": silver.get("event_id", ""),
                "raw_id": raw_id,
                "evidence_id": f"ev-{index:05d}",
                "platform": post.get("platform", ""),
                "url": post.get("url", ""),
                "timestamp": post.get("timestamp", ""),
                "source_type": post.get("source_type", "other"),
                "text": post.get("text", ""),
                "candidate_stakeholder": silver.get("stakeholder", ""),
                "candidate_opinion": silver.get("opinion", ""),
                "candidate_sentiment": silver.get("sentiment", ""),
                "candidate_rationale": silver.get("rationale", ""),
                "candidate_event_chain": silver.get("event_chain", []),
                "label_source": silver.get("label_source", "llm_silver"),
                "confidence": silver.get("confidence", 0.0),
            }
        )
    write_jsonl(pairs, output_path)
    return {"raw_posts_path": str(raw_posts_path), "silver_path": str(silver_path), "output_path": str(output_path), "num_candidate_pairs": len(pairs)}


def normalize_raw_post(row: dict[str, Any], *, index: int, stats: PrivacyFilterStats, provenance: str) -> dict[str, Any]:
    """Normalize an imported/crawled row into the raw_posts contract."""
    raw_id = str(row.get("raw_id") or row.get("id") or row.get("evidence_id") or _stable_id("raw", json.dumps(row, ensure_ascii=False), index))
    text = sanitize_text(str(row.get("text") or row.get("content") or row.get("snippet") or ""), stats)
    title = sanitize_text(str(row.get("title") or ""), stats)
    return {
        "raw_id": raw_id,
        "event_seed_id": str(row.get("event_seed_id") or row.get("event_id") or _event_seed_from_text(f"{title} {text}")),
        "platform": str(row.get("platform") or row.get("source") or "public_web"),
        "url": str(row.get("url") or ""),
        "timestamp": str(row.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        "title": title,
        "text": text,
        "source_type": str(row.get("source_type") or "other"),
        "crawl_method": str(row.get("crawl_method") or "import"),
        "provenance": provenance,
        "raw_metadata": {key: value for key, value in row.items() if key not in {"text", "content", "snippet", "title"}},
    }


def extract_page_text(content: str) -> tuple[str, str]:
    """Extract a conservative title/body from an HTML page or plain text."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, flags=re.IGNORECASE | re.DOTALL)
    title = html.unescape(_strip_tags(title_match.group(1))).strip() if title_match else ""
    text = html.unescape(_strip_tags(content))
    return title, " ".join(text.split())


def infer_stakeholder(text: str) -> str:
    lowered = text.lower()
    for stakeholder, hints in STAKEHOLDER_HINTS.items():
        if any(hint.lower() in lowered for hint in hints):
            return stakeholder
    return "public"


def infer_sentiment(text: str) -> str:
    lowered = text.lower()
    if any(term.lower() in lowered for term in MIXED_TERMS):
        return "mixed"
    if any(term.lower() in lowered for term in NEGATIVE_TERMS):
        return "negative"
    if any(term.lower() in lowered for term in POSITIVE_TERMS):
        return "positive"
    return "neutral"


def infer_opinion(text: str, stakeholder: str) -> str:
    compact = " ".join(text.split())
    return f"{stakeholder} view: {compact[:80]}" if compact else f"{stakeholder} view on urban renewal"


def infer_rationale(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:160] if compact else "Candidate rationale requires human verification."


def confidence_for_silver(text: str, stakeholder: str, sentiment: str) -> float:
    score = 0.4
    if stakeholder != "public":
        score += 0.2
    if sentiment != "neutral":
        score += 0.2
    if len(text.strip()) >= 30:
        score += 0.2
    return round(min(1.0, score), 4)


def _read_source_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    return load_jsonl(path)


def _http_get_text(url: str, timeout_seconds: float) -> str:
    response = httpx.get(url, timeout=timeout_seconds, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _host_from_url(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url)
    return match.group(1) if match else "public_web"


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _stable_id(prefix: str, value: str, index: int) -> str:
    digest = hashlib.sha256(f"{index}|{value}".encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _event_seed_from_text(text: str) -> str:
    compact = " ".join(text.split())
    for term in URBAN_RENEWAL_TERMS:
        if term.lower() in compact.lower():
            return term
    return compact[:40] or "urban_renewal"


def _target_event(seed: str, posts: list[dict[str, Any]]) -> str:
    for post in posts:
        title = str(post.get("title") or "").strip()
        if title:
            return title
    return f"Urban renewal discussion: {seed}"


def _event_chain_for_posts(posts: list[dict[str, Any]], target_event: str) -> list[str]:
    stages = [str(post.get("raw_metadata", {}).get("time_stage", "")).strip() for post in posts]
    stages = [stage for stage in stages if stage]
    if stages:
        return list(dict.fromkeys(stages))
    return [target_event, "public reaction", "official or stakeholder response"]


def _stakeholders_for_posts(posts: list[dict[str, Any]]) -> set[str]:
    return {infer_stakeholder(str(post.get("text") or "")) for post in posts}
