"""Event graph schemas for EpiSOA."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episoa.schemas.evidence import EvidenceRecord


class EventChain(BaseModel):
    """A candidate causal or temporal event chain with supporting evidence."""

    model_config = ConfigDict(extra="forbid")

    target_event: str = Field(..., min_length=1, description="The event whose causes or attribution are being analyzed.")
    event_chain: list[str] = Field(..., min_length=1, description="Ordered events related to the target event.")
    stakeholders: list[str] = Field(..., min_length=1, description="Stakeholders involved in or affected by the chain.")
    candidate_rationales: list[str] = Field(
        default_factory=list,
        description="Candidate natural-language explanations for the event chain.",
    )
    evidence: list[EvidenceRecord] = Field(
        default_factory=list,
        description="Evidence records supporting this event chain.",
    )

    @field_validator("target_event", mode="before")
    @classmethod
    def strip_target_event(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("target_event must be a string")
        value = value.strip()
        if not value:
            raise ValueError("target_event must not be blank")
        return value

    @field_validator("event_chain", "stakeholders", "candidate_rationales", mode="before")
    @classmethod
    def validate_non_blank_string_list(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("value must be a list")

        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError("list items must be strings")
            item = item.strip()
            if not item:
                raise ValueError("list items must not be blank")
            cleaned.append(item)
        return cleaned
