from datetime import datetime, timezone

from episoa.graph_builder.extractor import build_evidence_graph
from episoa.schemas.evidence import EvidenceRecord


def make_evidence(
    evidence_id: str,
    event: str,
    stakeholder: str,
    sentiment: str,
    day: int,
    **metadata: str,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        platform="Example News",
        url=f"https://example.com/{evidence_id}",
        timestamp=datetime(2026, 4, day, tzinfo=timezone.utc),
        text=f"{stakeholder} expressed a {sentiment} opinion about {event}.",
        author_alias=stakeholder,
        source_type="news",
        metadata={
            "event": event,
            "stakeholder": stakeholder,
            "opinion": f"{stakeholder} reacts to {event}",
            "sentiment": sentiment,
            "rationale": f"{stakeholder} rationale for {event}",
            **metadata,
        },
    )


def test_build_evidence_graph_writes_expected_node_types() -> None:
    graph = build_evidence_graph(
        [
            make_evidence("ev-1", "Policy change", "Customers", "negative", 1),
        ]
    )

    node_types = {attrs["node_type"] for _, attrs in graph.graph.nodes(data=True)}

    assert {
        "Event",
        "Stakeholder",
        "Opinion",
        "Sentiment",
        "Rationale",
        "Evidence",
        "Time",
    }.issubset(node_types)
    assert graph.has_evidence("ev-1")


def test_build_evidence_graph_writes_expected_edges_and_evidence_ids() -> None:
    graph = build_evidence_graph(
        [
            make_evidence(
                "ev-1",
                "Public criticism",
                "Customers",
                "negative",
                1,
                trigger_event="Price increase",
            ),
            make_evidence(
                "ev-2",
                "Company response",
                "Company",
                "neutral",
                2,
                responds_to="Public criticism",
                amplifies="Public criticism",
            ),
        ]
    )

    edge_types = {attrs["edge_type"] for _, _, attrs in graph.graph.edges(data=True)}
    evidence_node = graph.graph.nodes["evidence:ev-1"]
    edges_with_ev_2 = [
        attrs for _, _, attrs in graph.graph.edges(data=True) if attrs.get("evidence_id") == "ev-2"
    ]

    assert {
        "expresses",
        "has_sentiment",
        "caused_by",
        "evidenced_by",
        "appears_at",
        "precedes",
        "triggers",
        "responds_to",
        "amplifies",
    }.issubset(edge_types)
    assert evidence_node["evidence_id"] == "ev-1"
    assert edges_with_ev_2


def test_build_evidence_graph_respects_temporal_and_stakeholder_ablations() -> None:
    graph = build_evidence_graph(
        [
            make_evidence("ev-1", "Public criticism", "Customers", "negative", 1),
            make_evidence("ev-2", "Company response", "Company", "neutral", 2),
        ],
        include_temporal_edges=False,
        include_stakeholder_edges=False,
    )

    edge_types = {attrs["edge_type"] for _, _, attrs in graph.graph.edges(data=True)}

    assert "appears_at" not in edge_types
    assert "precedes" not in edge_types
    assert "expresses" not in edge_types


def test_build_evidence_graph_preserves_time_stage_and_source_scope_metadata() -> None:
    graph = build_evidence_graph(
        [
            make_evidence(
                "ev-1",
                "Public criticism",
                "Customers",
                "negative",
                1,
                time_stage="trigger",
                source_scope="forum",
            ),
        ]
    )

    evidence_node = graph.graph.nodes["evidence:ev-1"]

    assert evidence_node["time_stage"] == "trigger"
    assert evidence_node["source_scope"] == "forum"
