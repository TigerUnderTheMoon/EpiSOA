"""Privacy protection utilities for evidence normalization."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from episoa.schemas.evidence import EvidenceRecord


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4}(?!\d)"
)
ID_NUMBER_PATTERN = re.compile(r"\b(?:\d{15}|\d{17}[\dXx]|\d{3}-\d{2}-\d{4})\b")

AUTHOR_NAME_KEYS = {"author_name", "real_name", "display_name", "full_name"}
AUTHOR_ALIAS_KEYS = {"author_alias", "username", "handle", "screen_name"}
USER_PROFILE_URL_KEYS = {
    "author_url",
    "author_profile_url",
    "profile_url",
    "user_url",
    "user_homepage_url",
    "homepage_url",
}


def redact_sensitive_text(text: str) -> str:
    """Remove common sensitive identifiers from text."""
    text = EMAIL_PATTERN.sub("[EMAIL]", text)
    text = PHONE_PATTERN.sub("[PHONE]", text)
    text = ID_NUMBER_PATTERN.sub("[ID_NUMBER]", text)
    return text


def author_alias_from_name(author_name: str | None) -> str | None:
    """Convert a raw author name into a deterministic alias."""
    if author_name is None:
        return None
    author_name = author_name.strip()
    if not author_name:
        return None
    digest = hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:10]
    return f"author_{digest}"


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop private author fields and redact sensitive string metadata."""
    sanitized: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        normalized_key = key.strip().lower()
        if normalized_key in AUTHOR_NAME_KEYS or normalized_key in USER_PROFILE_URL_KEYS:
            continue
        if isinstance(value, str):
            sanitized[key] = redact_sensitive_text(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_metadata(value)
        elif isinstance(value, list):
            sanitized[key] = [
                redact_sensitive_text(item) if isinstance(item, str) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


def privacy_filter_raw_evidence(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a privacy-safe raw evidence dictionary.

    The canonical evidence URL is preserved. User profile/homepage URLs are
    removed from metadata and are not copied to the output.
    """
    metadata = sanitize_metadata(dict(raw.get("metadata") or {}))

    for key in USER_PROFILE_URL_KEYS:
        raw.pop(key, None)

    author_alias = raw.get("author_alias")
    if not author_alias:
        for key in AUTHOR_ALIAS_KEYS:
            if raw.get(key):
                author_alias = str(raw[key]).strip()
                break
    if not author_alias:
        for key in AUTHOR_NAME_KEYS:
            if raw.get(key):
                author_alias = author_alias_from_name(str(raw[key]))
                break

    safe: dict[str, Any] = {
        "evidence_id": raw.get("evidence_id"),
        "platform": raw.get("platform"),
        "url": raw.get("url"),
        "timestamp": raw.get("timestamp"),
        "text": redact_sensitive_text(str(raw.get("text", ""))),
        "author_alias": author_alias,
        "source_type": raw.get("source_type", "other"),
        "metadata": metadata,
    }
    return {key: value for key, value in safe.items() if value is not None}


def normalize_private_evidence(raw: dict[str, Any]) -> EvidenceRecord:
    """Apply privacy filtering and build an EvidenceRecord."""
    safe = privacy_filter_raw_evidence(dict(raw))
    timestamp = safe.get("timestamp")
    if isinstance(timestamp, str):
        safe["timestamp"] = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    elif timestamp is None:
        safe["timestamp"] = datetime.now(timezone.utc)
    return EvidenceRecord.model_validate(safe)
