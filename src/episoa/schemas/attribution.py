"""Attribution reasoning schemas for EpiSOA."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episoa.schemas.evidence import EvidenceRecord


SentimentLabel = Literal["positive", "negative", "neutral", "mixed", "unknown"]
SupportLabel = Literal["supported", "partially_supported", "unsupported", "insufficient_evidence"]


class AttributionTuple(BaseModel):
    """A structured stakeholder-opinion attribution result."""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(..., min_length=1, description="Event being attributed or explained.")
    stakeholder: str = Field(..., min_length=1, description="Stakeholder associated with the opinion.")
    opinion: str = Field(..., min_length=1, description="Opinion or stance attributed to the stakeholder.")
    sentiment: SentimentLabel = Field(..., description="Sentiment polarity of the stakeholder opinion.")
    rationale: str = Field(..., min_length=1, description="Natural-language rationale for the attribution.")
    event_chain: list[str] = Field(..., min_length=1, description="Relevant event chain used for attribution.")
    evidence: list[EvidenceRecord] = Field(..., min_length=1, description="Evidence supporting the attribution tuple.")
    support_score: float = Field(..., ge=0.0, le=1.0, description="Confidence score in the range [0, 1].")
    verified: bool = Field(False, description="Whether the tuple passed verification checks.")
    support_label: SupportLabel = Field("supported", description="Paper-facing evidence support label.")
    failure_reason: str | None = Field(None, description="Reason the tuple failed verification, if any.")

    @field_validator("event", "stakeholder", "opinion", "rationale", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("event_chain", mode="before")
    @classmethod
    def validate_event_chain(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("event_chain must be a list")

        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError("event_chain items must be strings")
            item = item.strip()
            if not item:
                raise ValueError("event_chain items must not be blank")
            cleaned.append(item)
        return cleaned
