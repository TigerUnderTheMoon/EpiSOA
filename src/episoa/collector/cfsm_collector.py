"""C-FSM Evidence Collector for local PubEvent-SOA evidence."""

from __future__ import annotations

from episoa.data.schema import EventRecord, EvidenceRecord


def collect_evidence(events: list[EventRecord], evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Return evidence linked to known events.

    The paper repository stores curated local evidence. This stage enforces the
    C-FSM collection boundary by filtering evidence to the configured event set.
    """
    event_ids = {event.event_id for event in events}
    return [item for item in evidence if item.event_id in event_ids]
