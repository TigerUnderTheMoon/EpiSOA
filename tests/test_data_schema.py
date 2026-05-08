from episoa.data.schema import EvidenceRecord, EventRecord, GoldEventChain, GoldTuple


def test_paper_schema_accepts_required_records() -> None:
    EventRecord(event_id="evt-1", event_name="Event")
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
