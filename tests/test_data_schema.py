from episoa.data.schema import EvidenceRecord, EventRecord, GoldEventChain, GoldTuple


def test_paper_schema_accepts_required_records() -> None:
    EventRecord(
        event_id="evt-1",
        domain="urban_renewal",
        event_type="concrete_event",
        event_name="Event",
        event_description="Concrete event",
        location={"province": "Test Province", "city": "Test City"},
        time_window={"start": "2025-01-01", "end": "2025-01-02"},
        trigger="Reported public decision",
        anchor_entities={"agency": "Test agency"},
        anchor_urls=["https://source.test/event"],
        source_scope=["news"],
        query_seeds=["test event"],
        stakeholder_hints=["Test agency", "Residents"],
        stance_hints=["support", "concern"],
        temporal_stages=["trigger", "response"],
    )
    EvidenceRecord(evidence_id="ev-1", event_id="evt-1", text="Evidence", platform="News", url="https://source.test")
    GoldTuple(
        event_id="evt-1",
        stakeholder="Residents",
        opinion="Opinion",
        sentiment="negative",
        rationale="Rationale",
        evidence_ids=["ev-1"],
        support_label="supported",
    )
    GoldEventChain(event_id="evt-1", event_chain=["Event"], evidence_ids=["ev-1"])
