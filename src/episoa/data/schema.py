"""Schemas for the PubEvent-SOA paper dataset and outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Sentiment = Literal["positive", "negative", "neutral", "mixed", "unknown"]
SupportLabel = Literal["supported", "partially_supported", "unsupported", "insufficient_evidence"]
Domain = Literal["urban_renewal", "education", "healthcare", "public_safety", "urban_mobility", "digital_governance"]
EventType = Literal["concrete_event", "issue_evolution"]
AnchorEntityValue = str | list[str]


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    domain: Domain
    event_type: EventType
    event_name: str = Field(..., min_length=1)
    event_description: str = Field(..., min_length=1)
    location: dict[str, Any] = Field(..., min_length=1)
    time_window: dict[str, Any] = Field(..., min_length=1)
    trigger: str = Field(..., min_length=1)
    anchor_entities: dict[str, AnchorEntityValue] = Field(..., min_length=1)
    anchor_urls: list[str] = Field(..., min_length=1)
    source_scope: list[str] = Field(..., min_length=1)
    query_seeds: list[str] = Field(..., min_length=1)
    stakeholder_hints: list[str] = Field(..., min_length=1)
    stance_hints: list[str] = Field(..., min_length=1)
    temporal_stages: list[str] = Field(..., min_length=1)

    @property
    def text(self) -> str:
        return self.event_name or self.event_description or ""


class RawPost(BaseModel):
    model_config = ConfigDict(extra="allow")

    raw_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    query_round: int = 0
    source: str = Field(..., min_length=1)
    platform: str = Field(..., min_length=1)
    publish_time: str | None = None
    url: str | None = None
    title: str | None = None
    snippet: str | None = None
    text: str = Field(..., min_length=1)
    collected_at: str = Field(..., min_length=1)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidence_id: str = Field(..., min_length=1)
    event_id: str = Field(..., min_length=1)
    source: str | None = None
    platform: str | None = None
    publish_time: str | None = None
    url: str | None = None
    text: str = Field(..., min_length=1)
    stakeholder_hint: str | None = None
    stance_hint: str | None = None
    temporal_stage: str | None = None
    traceable: bool = False


class GoldTuple(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(..., min_length=1)
    stakeholder: str = Field(..., min_length=1)
    opinion: str = Field(..., min_length=1)
    sentiment: Sentiment
    rationale: str = Field(..., min_length=1)
    evidence_ids: list[str] = Field(..., min_length=1)
    support_label: SupportLabel


class GoldEventChain(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(..., min_length=1)
    event_chain: list[str] | None = None
    chain_nodes: list[str] | None = None
    evidence_ids: list[str] = Field(..., min_length=1)

    @property
    def nodes(self) -> list[str]:
        return self.event_chain or self.chain_nodes or []


class PredictionTuple(GoldTuple):
    support_score: float = 0.0
    verified: bool = False
