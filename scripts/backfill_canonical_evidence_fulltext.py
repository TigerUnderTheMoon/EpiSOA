"""Backfill canonical evidence text by fetching each evidence URL."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

import httpx

from episoa.data.loader import read_jsonl, read_typed_jsonl, write_jsonl
from episoa.data.schema import EvidenceRecord


DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
DEFAULT_AUDIT_ROOT = Path("data/pubevent_soa_lite/interim")
DEFAULT_REF_ROOTS = [Path("data/pubevent_soa_lite"), Path("data/benchmark")]
SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "header", "aside"}
TEXT_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
)
BINARY_CONTENT_TYPES = (
    "application/pdf",
    "application/msword",
    "application/octet-stream",
    "application/vnd.",
    "image/",
    "audio/",
    "video/",
)
BINARY_MAGIC_PREFIXES = (b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")
CAPTCHA_HINTS = (
    "验证码",
    "安全验证",
    "人机验证",
    "访问验证",
    "访问过于频繁",
    "拖动滑块",
    "滑块验证",
    "captcha",
    "security check",
    "verify you are human",
    "checking your browser",
)
NAV_HINTS = ("首页", "导航", "登录", "注册", "菜单", "搜索", "友情链接", "联系我们", "返回首页", "版权所有", "备案")
INFO_HINTS = (
    "回应",
    "回复",
    "通报",
    "公告",
    "投诉",
    "反映",
    "质疑",
    "表示",
    "称",
    "认为",
    "要求",
    "处理",
    "整改",
    "调查",
    "补偿",
    "安置",
    "业主",
    "居民",
    "网友",
    "政府",
    "部门",
    "街道",
    "企业",
)
DATE_PATTERN = re.compile(r"(20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}[-/]\d{1,2}[-/]\d{1,2})")
CHINESE_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")
BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
    "ol",
}


@dataclass(frozen=True)
class FetchOutcome:
    status: str
    text: str = ""
    reason: str = ""
    http_status: int | None = None
    final_url: str | None = None
    content_type: str | None = None


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if data and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return normalize_text("".join(self.parts))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill canonical evidence with fetched URL full text.")
    parser.add_argument("--input", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--output", default=None, help="Output JSONL. Defaults to input when --in-place is set.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--audit-root", default=str(DEFAULT_AUDIT_ROOT))
    parser.add_argument("--threshold", type=int, default=15)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--in-place", action="store_true", help="Backup and replace the input file after validation.")
    parser.add_argument("--dry-run", action="store_true", help="Write audit artifacts only; do not replace input.")
    parser.add_argument("--ref-root", action="append", default=None, help="Root to scan for deleted evidence refs.")
    return parser


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    in_place = bool(args.in_place)
    dry_run = bool(args.dry_run)
    if output_path == input_path and not in_place and not dry_run:
        raise SystemExit("Refusing to overwrite input without --in-place or --dry-run.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    audit_dir = Path(args.audit_root) / f"fulltext_backfill_{timestamp}"
    audit_dir.mkdir(parents=True, exist_ok=True)

    rows = read_jsonl(input_path)
    if args.limit is not None:
        rows = rows[: args.limit]

    fetched_at = datetime.now(timezone.utc).isoformat()
    kept: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()

    processed: list[tuple[int, dict[str, Any] | None, dict[str, Any] | None, FetchOutcome]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = {
            executor.submit(
                fetch_record,
                row,
                event_terms=event_terms_for_row(row, args.events),
                timeout_seconds=float(args.timeout_seconds),
                retries=int(args.retries),
            ): (
                index,
                row,
            )
            for index, row in enumerate(rows, start=1)
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            index, row = futures[future]
            outcome = future.result()
            status_counts[outcome.status] += 1
            if outcome.status != "ok":
                reason = outcome.reason or outcome.status
                reason_counts[reason] += 1
                processed.append((index, None, deleted_row(row, reason, outcome), outcome))
            else:
                processed.append((index, backfilled_row(row, outcome, fetched_at), None, outcome))
            if completed % 50 == 0:
                kept_count = sum(1 for _, kept_row, _, _ in processed if kept_row is not None)
                print(
                    f"[backfill] processed={completed} kept={kept_count} deleted={len(processed) - kept_count}",
                    flush=True,
                )

    for _, kept_row, deleted_item, _ in sorted(processed, key=lambda item: item[0]):
        if kept_row is not None:
            kept.append(kept_row)
        elif deleted_item is not None:
            deleted.append(deleted_item)

    per_event_counts = dict(sorted(Counter(str(row.get("event_id") or "") for row in kept).items()))
    below_threshold = [
        {"event_id": event_id, "usable_evidence_count": count}
        for event_id, count in per_event_counts.items()
        if count < int(args.threshold)
    ]
    missing_events = events_with_no_evidence(args.events, per_event_counts)
    for event_id in missing_events:
        below_threshold.append({"event_id": event_id, "usable_evidence_count": 0})

    deleted_ids = {str(row.get("evidence_id")) for row in deleted if row.get("evidence_id")}
    dangling_refs = find_deleted_evidence_refs(
        deleted_ids,
        [Path(root) for root in (args.ref_root or DEFAULT_REF_ROOTS)],
        exclude={input_path.resolve(), audit_dir.resolve()},
    )

    write_jsonl(audit_dir / "backfilled_evidence.preview.jsonl", kept)
    write_jsonl(audit_dir / "deleted_evidence.jsonl", deleted)
    write_jsonl(audit_dir / "events_below_threshold.jsonl", event_rows_for_ids(Path(args.events), below_threshold))
    write_jsonl(audit_dir / "deleted_evidence_refs.jsonl", dangling_refs)
    report = {
        "input": str(input_path),
        "output": str(output_path),
        "dry_run": dry_run,
        "in_place": in_place,
        "processed_rows": len(rows),
        "kept_rows": len(kept),
        "deleted_rows": len(deleted),
        "status_counts": dict(status_counts),
        "delete_reason_counts": dict(reason_counts),
        "threshold": int(args.threshold),
        "event_count_after": len(per_event_counts),
        "per_event_usable_evidence_count": per_event_counts,
        "events_below_threshold": sorted(below_threshold, key=lambda row: (row["usable_evidence_count"], row["event_id"])),
        "deleted_evidence_ref_count": len(dangling_refs),
        "audit_dir": str(audit_dir),
    }
    write_json(audit_dir / "fulltext_backfill_report.json", report)

    if dry_run:
        print(f"dry-run wrote audit artifacts to {audit_dir}")
        return 0

    validate_output(kept)
    temp_path = output_path.with_name(output_path.name + f".tmp_fulltext_backfill_{timestamp}")
    write_jsonl(temp_path, kept)
    read_typed_jsonl(temp_path, EvidenceRecord)

    if in_place:
        backup_path = input_path.with_name(input_path.name + f".bak_before_fulltext_backfill_{timestamp}")
        shutil.copy2(input_path, backup_path)
        temp_path.replace(input_path)
        report["backup_path"] = str(backup_path)
        report["replaced_path"] = str(input_path)
        write_json(audit_dir / "fulltext_backfill_report.json", report)
        print(f"replaced {input_path}; backup: {backup_path}")
    else:
        temp_path.replace(output_path)
        report["written_path"] = str(output_path)
        write_json(audit_dir / "fulltext_backfill_report.json", report)
        print(f"wrote {output_path}")
    print(f"audit_dir: {audit_dir}")
    return 0


def fetch_fulltext(
    client: httpx.Client,
    url: str,
    *,
    event_terms: list[str] | None = None,
    retries: int,
) -> FetchOutcome:
    if not url.strip():
        return FetchOutcome(status="deleted", reason="missing_url")
    last_reason = "fetch_failed"
    for attempt in range(retries + 1):
        try:
            response = client.get(url)
        except httpx.TimeoutException:
            last_reason = "timeout"
            continue
        except httpx.HTTPError as exc:
            last_reason = type(exc).__name__
            continue
        if response.status_code >= 400:
            return FetchOutcome(
                status="deleted",
                reason=f"http_status_{response.status_code}",
                http_status=response.status_code,
                final_url=str(response.url),
                content_type=response.headers.get("content-type"),
            )
        content_type = response.headers.get("content-type")
        if is_binary_response(response.content, content_type):
            return FetchOutcome(
                status="deleted",
                reason="binary_content_type",
                http_status=response.status_code,
                final_url=str(response.url),
                content_type=content_type,
            )
        text = extract_text(decode_response_text(response))
        unusable_reason = unusable_text_reason(text, event_terms or [])
        if unusable_reason:
            return FetchOutcome(
                status="deleted",
                reason=unusable_reason,
                http_status=response.status_code,
                final_url=str(response.url),
                content_type=content_type,
            )
        if text:
            return FetchOutcome(
                status="ok",
                text=text,
                http_status=response.status_code,
                final_url=str(response.url),
                content_type=content_type,
            )
        last_reason = "empty_extracted_text"
        if attempt < retries:
            continue
        return FetchOutcome(
            status="deleted",
            reason=last_reason,
            http_status=response.status_code,
            final_url=str(response.url),
            content_type=content_type,
        )
    return FetchOutcome(status="deleted", reason=last_reason)


def fetch_record(
    row: dict[str, Any],
    *,
    event_terms: list[str],
    timeout_seconds: float,
    retries: int,
) -> FetchOutcome:
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_seconds),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        },
    ) as client:
        return fetch_fulltext(client, str(row.get("url") or ""), event_terms=event_terms, retries=retries)


def is_binary_response(content: bytes, content_type: str | None) -> bool:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized.startswith(BINARY_CONTENT_TYPES):
        return True
    sample = content[:16]
    return any(sample.startswith(prefix) for prefix in BINARY_MAGIC_PREFIXES)


def decode_response_text(response: httpx.Response) -> str:
    content = response.content
    candidates = [
        response.encoding,
        charset_from_content_type(response.headers.get("content-type")),
        "utf-8",
        "gb18030",
        "gbk",
    ]
    decoded: list[tuple[float, str]] = []
    for encoding in dedupe([item for item in candidates if item]):
        try:
            text = content.decode(str(encoding), errors="replace")
        except LookupError:
            continue
        decoded.append((decode_penalty(text), text))
    if not decoded:
        return response.text
    return min(decoded, key=lambda item: item[0])[1]


def charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def decode_penalty(text: str) -> float:
    if not text:
        return 100.0
    replacement = text.count("\ufffd") / max(len(text), 1)
    mojibake = sum(text.count(marker) for marker in ("Ã", "Â", "锟", "�"))
    return replacement * 100 + mojibake / max(len(text), 1)


def unusable_text_reason(text: str, event_terms: list[str]) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "empty_extracted_text"
    lowered = normalized.lower()
    if any(hint.lower() in lowered for hint in CAPTCHA_HINTS):
        return "captcha_or_verification"
    if looks_binary_text(normalized):
        return "binary_or_decode_failed"
    has_signal = has_information_signal(normalized, event_terms)
    nav_hits = sum(1 for hint in NAV_HINTS if hint in normalized)
    if len(normalized) < 300 and nav_hits >= 3 and not has_signal:
        return "navigation_only"
    if len(normalized) < 20:
        return "too_short"
    if len(normalized) < 80 and not has_signal:
        return "short_no_information"
    return ""


def looks_binary_text(text: str) -> bool:
    sample = text[:1000]
    if not sample:
        return False
    control_count = sum(1 for char in sample if ord(char) < 32 and char not in "\n\r\t")
    replacement_ratio = sample.count("\ufffd") / len(sample)
    return control_count > 5 or replacement_ratio > 0.03


def has_information_signal(text: str, event_terms: list[str]) -> bool:
    if DATE_PATTERN.search(text):
        return True
    if any(hint in text for hint in INFO_HINTS):
        return True
    terms = [term for term in event_terms if len(term) >= 2]
    return any(term in text for term in terms[:80])


def event_terms_for_row(row: dict[str, Any], events_path: str | Path) -> list[str]:
    # Tiny datasets make repeated reads acceptable and keep worker inputs simple.
    if not hasattr(event_terms_for_row, "_cache"):
        path = Path(events_path)
        events = read_jsonl(path) if path.exists() else []
        setattr(event_terms_for_row, "_cache", build_event_terms(events))
    cache = getattr(event_terms_for_row, "_cache")
    return cache.get(str(row.get("event_id") or ""), [])


def build_event_terms(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {str(event.get("event_id") or ""): event_terms(event) for event in events}


def event_terms(event: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("event_name", "event_description", "trigger"):
        values.extend(flatten_strings(event.get(key)))
    for key in ("anchor_entities", "query_seeds", "stakeholder_hints", "stance_hints", "temporal_stages", "location"):
        values.extend(flatten_strings(event.get(key)))
    terms: list[str] = []
    for value in values:
        terms.append(value)
        terms.extend(CHINESE_TOKEN_PATTERN.findall(value))
    return dedupe([term.strip() for term in terms if term and len(term.strip()) >= 2])


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        output: list[str] = []
        for item in value.values():
            output.extend(flatten_strings(item))
        return output
    if isinstance(value, list):
        output = []
        for item in value:
            output.extend(flatten_strings(item))
        return output
    return []


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def extract_text(html: str) -> str:
    paragraph_text = extract_paragraph_text(html)
    if paragraph_text:
        return paragraph_text
    for fragment in candidate_html_fragments(html):
        text = extract_text_fragment(fragment)
        if text:
            return text
    return extract_text_fragment(html)


def extract_text_fragment(html: str) -> str:
    extractor = TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception:
        return normalize_text(strip_tags(html))
    return extractor.text()


def extract_paragraph_text(html: str) -> str:
    paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", html, flags=re.IGNORECASE | re.DOTALL)
    texts = [extract_text_fragment(fragment) for fragment in paragraphs]
    return normalize_text("\n".join(text for text in texts if text))


def candidate_html_fragments(html: str) -> list[str]:
    candidates: list[tuple[int, str]] = []
    patterns = [
        r"<article\b[^>]*>(.*?)</article>",
        r"<main\b[^>]*>(.*?)</main>",
        (
            r"<(?P<tag>div|section)\b[^>]*(?:id|class)\s*=\s*['\"][^'\"]*"
            r"(?:article|content|detail|main|text|news|zoom|TRS_Editor|正文)"
            r"[^'\"]*['\"][^>]*>(?P<body>.*?)</(?P=tag)>"
        ),
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE | re.DOTALL):
            body = match.groupdict().get("body") or match.group(1)
            text = extract_text_fragment(body)
            if text:
                candidates.append((len(text), body))
    return [body for _, body in sorted(candidates, key=lambda item: item[0], reverse=True)]


def normalize_text(value: str) -> str:
    text = value.replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n").replace("\x85", "\n")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def backfilled_row(row: dict[str, Any], outcome: FetchOutcome, fetched_at: str) -> dict[str, Any]:
    output = dict(row)
    legacy_text = str(row.get("text") or "")
    text = outcome.text.strip()
    output["legacy_text"] = legacy_text
    output["text"] = text
    output["fulltext_backfill_status"] = "ok"
    output["fulltext_chars"] = len(text)
    output["fulltext_fetched_at"] = fetched_at
    output["fulltext_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    output["fulltext_final_url"] = outcome.final_url
    output["fulltext_content_type"] = outcome.content_type
    return output


def deleted_row(row: dict[str, Any], reason: str, outcome: FetchOutcome) -> dict[str, Any]:
    return {
        "evidence_id": row.get("evidence_id"),
        "event_id": row.get("event_id"),
        "url": row.get("url"),
        "source": row.get("source"),
        "source_type": row.get("source_type"),
        "legacy_text": row.get("text"),
        "delete_reason": reason,
        "http_status": outcome.http_status,
        "final_url": outcome.final_url,
        "content_type": outcome.content_type,
    }


def validate_output(rows: list[dict[str, Any]]) -> None:
    ids = [str(row.get("evidence_id") or "") for row in rows]
    duplicate_ids = [evidence_id for evidence_id, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        raise SystemExit(f"duplicate evidence_id in output: {duplicate_ids[:10]}")
    empty_text = [str(row.get("evidence_id")) for row in rows if not str(row.get("text") or "").strip()]
    if empty_text:
        raise SystemExit(f"empty text in output: {empty_text[:10]}")


def events_with_no_evidence(events_path: str | Path, per_event_counts: dict[str, int]) -> list[str]:
    path = Path(events_path)
    if not path.exists():
        return []
    event_ids = [str(row.get("event_id") or "") for row in read_jsonl(path)]
    return [event_id for event_id in event_ids if event_id and event_id not in per_event_counts]


def event_rows_for_ids(events_path: Path, below_threshold: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []
    needed = {str(row["event_id"]) for row in below_threshold}
    rows = []
    counts = {str(row["event_id"]): int(row["usable_evidence_count"]) for row in below_threshold}
    for event in read_jsonl(events_path):
        event_id = str(event.get("event_id") or "")
        if event_id in needed:
            output = dict(event)
            output["usable_evidence_count_after_fulltext_backfill"] = counts[event_id]
            rows.append(output)
    return rows


def find_deleted_evidence_refs(
    deleted_ids: set[str],
    roots: list[Path],
    *,
    exclude: set[Path],
) -> list[dict[str, Any]]:
    if not deleted_ids:
        return []
    refs: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".jsonl", ".json"}:
                continue
            resolved = path.resolve()
            if resolved in exclude or any(parent in exclude for parent in resolved.parents):
                continue
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            refs.extend(scan_refs_in_file(path, deleted_ids))
    return refs


def scan_refs_in_file(path: Path, deleted_ids: set[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if path.suffix.lower() == ".jsonl":
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            hits = sorted(find_ids(obj) & deleted_ids)
            if hits:
                refs.append({"path": str(path), "line": line_number, "deleted_evidence_ids": hits})
    elif path.suffix.lower() == ".json":
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return refs
        hits = sorted(find_ids(obj) & deleted_ids)
        if hits:
            refs.append({"path": str(path), "line": None, "deleted_evidence_ids": hits})
    return refs


def find_ids(value: Any) -> set[str]:
    output: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"evidence_id", "evidence_ids", "gold_evidence_ids", "selected_evidence_ids"}:
                output.update(as_id_set(item))
            output.update(find_ids(item))
    elif isinstance(value, list):
        for item in value:
            output.update(find_ids(item))
    return output


def as_id_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value if str(item).strip()}
    return set()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
