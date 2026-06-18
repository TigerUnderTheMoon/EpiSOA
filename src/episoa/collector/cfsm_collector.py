"""C-FSM Evidence Collector for local PubEvent-SOA evidence."""

from __future__ import annotations

from episoa.data.schema import EventRecord, EvidenceRecord


def filter_evidence_by_events(events: list[EventRecord], evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Filter evidence records by event IDs.

    Note: actual collection logic is in scripts/collect_evidence.py.
    """
    event_ids = {event.event_id for event in events}
    return [item for item in evidence if item.event_id in event_ids]
