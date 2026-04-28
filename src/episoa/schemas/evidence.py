"""Evidence data schemas for EpiSOA."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


SourceType = Literal["news", "social_media", "official", "blog", "forum", "other"]


class EvidenceRecord(BaseModel):
    """A normalized evidence item collected from an external source."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1, description="Unique identifier for this evidence record.")
    platform: str = Field(..., min_length=1, description="Source platform name, such as X, Reddit, or a news outlet.")
    url: HttpUrl = Field(..., description="Canonical URL where the evidence was collected.")
    timestamp: datetime = Field(..., description="Publication or collection timestamp for the evidence.")
    text: str = Field(..., min_length=1, description="Evidence text content used for downstream reasoning.")
    author_alias: str | None = Field(None, description="Public alias or anonymized identifier of the author.")
    source_type: SourceType = Field(..., description="High-level category of the source.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional structured attributes from collection.")

    @field_validator("evidence_id", "platform", "text", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Reject strings that are empty after trimming whitespace."""
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("author_alias", mode="before")
    @classmethod
    def normalize_optional_author(cls, value: str | None) -> str | None:
        """Convert blank author aliases to None."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("author_alias must be a string or None")
        value = value.strip()
        return value or None
