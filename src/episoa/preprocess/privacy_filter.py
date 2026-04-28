"""Privacy filtering for semi-real public evidence snippets."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4}(?!\d)")
CN_ID_RE = re.compile(r"\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b")
HANDLE_RE = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{2,32}\b")
PROFILE_KEYWORDS = ("profile", "homepage", "home_url", "user_url", "author_url", "author_profile")
SENSITIVE_METADATA_KEYWORDS = ("author_name", "author_username", "username", "email", "phone", "id_number", "id_card")


@dataclass
class PrivacyFilterStats:
    """Counts produced while cleaning semi-real evidence."""

    total_records: int = 0
    cleaned_records: int = 0
    skipped_records: int = 0
    emails_removed: int = 0
    phones_removed: int = 0
    id_numbers_removed: int = 0
    handles_removed: int = 0
    profile_urls_removed: int = 0
    author_aliases_created: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "cleaned_records": self.cleaned_records,
            "skipped_records": self.skipped_records,
            "emails_removed": self.emails_removed,
            "phones_removed": self.phones_removed,
            "id_numbers_removed": self.id_numbers_removed,
            "handles_removed": self.handles_removed,
            "profile_urls_removed": self.profile_urls_removed,
            "author_aliases_created": self.author_aliases_created,
            "errors": self.errors,
        }


def sanitize_text(text: str, stats: PrivacyFilterStats | None = None) -> str:
    """Remove common direct identifiers from text."""
    if not isinstance(text, str):
        text = str(text)

    text, emails = EMAIL_RE.subn("[REDACTED_EMAIL]", text)
    text, phones = PHONE_RE.subn("[REDACTED_PHONE]", text)
    text, ids = CN_ID_RE.subn("[REDACTED_ID]", text)
    text, handles = HANDLE_RE.subn("[REDACTED_HANDLE]", text)

    if stats is not None:
        stats.emails_removed += emails
        stats.phones_removed += phones
        stats.id_numbers_removed += ids
        stats.handles_removed += handles
    return " ".join(text.split())


def make_author_alias(raw_author: str | None, fallback_id: str) -> str | None:
    """Convert a raw author name or username into a stable anonymous alias."""
    author = (raw_author or "").strip()
    if not author:
        return None
    digest = hashlib.sha256(f"{fallback_id}|{author}".encode("utf-8")).hexdigest()[:12]
    return f"author_{digest}"


def clean_metadata(metadata: dict[str, Any] | None, stats: PrivacyFilterStats | None = None) -> dict[str, Any]:
    """Drop direct identifiers and user homepage/profile URLs from metadata."""
    cleaned: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        lowered = key.lower()
        if any(token in lowered for token in PROFILE_KEYWORDS):
            if stats is not None:
                stats.profile_urls_removed += 1
            continue
        if any(token in lowered for token in SENSITIVE_METADATA_KEYWORDS):
            continue
        if isinstance(value, str):
            cleaned[key] = sanitize_text(value, stats)
        else:
            cleaned[key] = value
    return cleaned


def clean_raw_evidence(raw: dict[str, Any], stats: PrivacyFilterStats | None = None) -> dict[str, Any]:
    """Convert a raw public snippet into an EvidenceRecord-compatible dictionary."""
    local_stats = stats or PrivacyFilterStats()
    local_stats.total_records += 1

    evidence_id = str(raw.get("evidence_id") or raw.get("id") or "").strip()
    if not evidence_id:
        local_stats.skipped_records += 1
        local_stats.errors.append("missing evidence_id")
        raise ValueError("raw evidence must include evidence_id")

    raw_author = raw.get("author_name") or raw.get("author_username") or raw.get("username") or raw.get("author_alias")
    author_alias = make_author_alias(str(raw_author), evidence_id) if raw_author else raw.get("author_alias")
    if raw_author and stats is not None:
        stats.author_aliases_created += 1
    if raw.get("author_profile_url") and stats is not None:
        stats.profile_urls_removed += 1

    metadata = clean_metadata(raw.get("metadata", {}), local_stats)
    event_id = raw.get("event_id")
    if event_id:
        metadata["event_id"] = str(event_id)
    metadata["privacy_filtered"] = True
    metadata["raw_evidence_id"] = evidence_id

    cleaned = {
        "evidence_id": evidence_id,
        "platform": str(raw.get("platform") or "public_web").strip(),
        "url": str(raw.get("url") or "").strip(),
        "timestamp": raw.get("timestamp"),
        "text": sanitize_text(str(raw.get("text") or raw.get("snippet") or ""), local_stats),
        "author_alias": author_alias,
        "source_type": str(raw.get("source_type") or "other").strip(),
        "metadata": metadata,
    }
    local_stats.cleaned_records += 1
    return cleaned
