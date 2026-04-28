"""Direct LLM-style baseline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from episoa.reasoner.attribution_reasoner import reason_attribution
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord
from episoa.schemas.graph import EventChain
from episoa.verifier.evidence_support import verify_attributions


def run(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    """Run direct attribution without reading the evidence pool."""
    config = config or {}
    llm_client = config.get("llm_client")
    verifier_threshold = float(config.get("verifier_threshold", 0.75))
    event_description = event_description_from(event)
    synthetic_evidence = [_synthetic_event_evidence(event_description)]
    event_chain = event_chain_from_event(event_description, synthetic_evidence)
    attributions = reason_attribution(event_chain, synthetic_evidence, event_description, llm_client=llm_client)
    return verify_attributions(
        attributions,
        synthetic_evidence,
        llm_client=llm_client,
        threshold=verifier_threshold,
    )


def run_baseline(
    event: str | dict[str, Any],
    evidence_pool: list[EvidenceRecord],
    config: dict[str, Any] | None = None,
) -> list[AttributionTuple]:
    """Backward-compatible alias for the unified baseline interface."""
    return run(event, evidence_pool, config)


def event_description_from(event: str | dict[str, Any]) -> str:
    if isinstance(event, dict):
        return str(event.get("target_event") or event.get("event_description") or event.get("event") or "").strip()
    return str(event).strip()


def event_chain_from_event(event_description: str, evidence: list[EvidenceRecord]) -> EventChain:
    return EventChain(
        target_event=event_description,
        event_chain=[event_description],
        stakeholders=sorted(
            {
                str(item.metadata.get("stakeholder") or item.author_alias or "unknown")
                for item in evidence
            }
        )
        or ["unknown"],
        candidate_rationales=["Direct LLM baseline uses only the event description."],
        evidence=evidence,
    )


def event_chain_from_evidence(event_description: str, evidence_pool: list[EvidenceRecord]) -> EventChain:
    events = [
        str(item.metadata.get("event"))
        for item in evidence_pool
        if item.metadata.get("event")
    ] or [event_description]
    stakeholders = sorted(
        {
            str(item.metadata.get("stakeholder") or item.author_alias or "unknown")
            for item in evidence_pool
        }
    ) or ["unknown"]
    return EventChain(
        target_event=event_description,
        event_chain=list(dict.fromkeys(events)),
        stakeholders=stakeholders,
        candidate_rationales=["Direct baseline uses all evidence without retrieval."],
        evidence=evidence_pool,
    )


def _synthetic_event_evidence(event_description: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="direct-llm-event-only",
        platform="direct_llm",
        url="https://example.com/baselines/direct-llm-event-only",
        timestamp=datetime(1970, 1, 1, tzinfo=timezone.utc),
        text=f"Event-only baseline input: {event_description}",
        author_alias="direct_llm",
        source_type="other",
        metadata={
            "stakeholder": "unknown",
            "sentiment": "unknown",
            "opinion": f"Event-only attribution for {event_description}",
            "event": event_description,
            "baseline": "direct_llm",
            "uses_evidence_pool": False,
        },
    )
