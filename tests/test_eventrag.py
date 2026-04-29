from datetime import datetime, timezone

from episoa.eventrag.anchor_selection import select_anchor_events
from episoa.eventrag.chain_expansion import EventPath, expand_event_chains
from episoa.eventrag.evidence_backtracking import backtrack_evidence
from episoa.eventrag.path_reranking import retrieve_event_chains, rerank_paths, score_path
from episoa.eventrag.query_to_event import parse_query_to_event
from episoa.graph_builder.graph_store import EvidenceGraph


def add_event(graph: EvidenceGraph, node_id: str, label: str) -> None:
    graph.add_node(node_id, "Event", label=label)


def add_evidence(
    graph: EvidenceGraph,
    event_id: str,
    evidence_id: str,
    day: int,
    stakeholder: str = "Customers",
) -> None:
    evidence_node = f"evidence:{evidence_id}"
    time_node = f"time:{evidence_id}"
    stakeholder_node = f"stakeholder:{stakeholder.lower()}"
    opinion_node = f"opinion:{evidence_id}"

    graph.add_node(
        evidence_node,
        "Evidence",
        evidence_id=evidence_id,
        platform="Example",
        url=f"https://example.com/{evidence_id}",
        text=f"{stakeholder} evidence for {event_id}",
        source_type="news",
    )
    graph.add_node(
        time_node,
        "Time",
        label=datetime(2026, 4, day, tzinfo=timezone.utc).isoformat(),
    )
    graph.add_node(stakeholder_node, "Stakeholder", label=stakeholder)
    graph.add_node(opinion_node, "Opinion", label=f"{stakeholder} opinion", evidence_id=evidence_id)
    graph.add_edge(event_id, evidence_node, "evidenced_by", evidence_id=evidence_id)
    graph.add_edge(evidence_node, time_node, "appears_at", evidence_id=evidence_id)
    graph.add_edge(stakeholder_node, opinion_node, "expresses", evidence_id=evidence_id)


def test_eventrag_expands_two_hop_path_from_anchor() -> None:
    graph = EvidenceGraph()
    add_event(graph, "event:alpha", "Alpha incident")
    add_event(graph, "event:beta", "Beta response")
    add_event(graph, "event:gamma", "Gamma amplification")
    graph.add_edge("event:alpha", "event:beta", "triggers", evidence_id="ev-1")
    graph.add_edge("event:beta", "event:gamma", "amplifies", evidence_id="ev-2")

    query_event = parse_query_to_event("Alpha incident")
    anchors = select_anchor_events(query_event, graph, top_k=1)
    paths = expand_event_chains(graph, anchors, depth=2)

    assert EventPath(
        node_ids=("event:alpha", "event:beta", "event:gamma"),
        edge_types=("triggers", "amplifies"),
    ) in paths


def test_paths_without_evidence_are_downweighted() -> None:
    graph = EvidenceGraph()
    add_event(graph, "event:policy-a", "Policy start")
    add_event(graph, "event:policy-b", "Policy response")
    add_event(graph, "event:policy-c", "Policy alternative")
    graph.add_edge("event:policy-a", "event:policy-b", "triggers", evidence_id="ev-1")
    graph.add_edge("event:policy-a", "event:policy-c", "triggers")
    add_evidence(graph, "event:policy-a", "ev-1", 1, "Customers")
    add_evidence(graph, "event:policy-b", "ev-2", 2, "Employees")

    supported = backtrack_evidence(graph, EventPath(("event:policy-a", "event:policy-b"), ("triggers",)))
    unsupported = backtrack_evidence(graph, EventPath(("event:policy-a", "event:policy-c"), ("triggers",)))

    assert score_path("policy", graph, supported).score > score_path("policy", graph, unsupported).score


def test_temporal_order_errors_are_downweighted() -> None:
    graph = EvidenceGraph()
    add_event(graph, "event:correct-a", "Policy start")
    add_event(graph, "event:correct-b", "Policy response")
    add_event(graph, "event:wrong-a", "Policy start")
    add_event(graph, "event:wrong-b", "Policy response")
    graph.add_edge("event:correct-a", "event:correct-b", "precedes", evidence_id="ev-1")
    graph.add_edge("event:wrong-a", "event:wrong-b", "precedes", evidence_id="ev-3")
    add_evidence(graph, "event:correct-a", "ev-1", 1, "Customers")
    add_evidence(graph, "event:correct-b", "ev-2", 2, "Employees")
    add_evidence(graph, "event:wrong-a", "ev-3", 4, "Customers")
    add_evidence(graph, "event:wrong-b", "ev-4", 3, "Employees")

    correct = backtrack_evidence(graph, EventPath(("event:correct-a", "event:correct-b"), ("precedes",)))
    wrong = backtrack_evidence(graph, EventPath(("event:wrong-a", "event:wrong-b"), ("precedes",)))

    assert score_path("policy", graph, correct).temporal_coherence == 1.0
    assert score_path("policy", graph, wrong).temporal_coherence == 0.0
    assert score_path("policy", graph, correct).score > score_path("policy", graph, wrong).score


def test_retrieve_event_chains_returns_schema() -> None:
    graph = EvidenceGraph()
    add_event(graph, "event:alpha", "Alpha incident")
    add_event(graph, "event:beta", "Beta response")
    graph.add_edge("event:alpha", "event:beta", "triggers", evidence_id="ev-1")
    add_evidence(graph, "event:alpha", "ev-1", 1, "Customers")
    add_evidence(graph, "event:beta", "ev-2", 2, "Employees")

    chains = retrieve_event_chains("Alpha incident", graph, depth=2, top_k=1, anchor_top_k=1)

    assert chains[0].target_event == "Alpha incident"
    assert chains[0].event_chain == ["Alpha incident", "Beta response"]
    assert {record.evidence_id for record in chains[0].evidence} == {"ev-1", "ev-2"}
    assert "stakeholder_coverage=" in chains[0].candidate_rationales[0]


def test_stakeholder_constraint_changes_path_ranking_features() -> None:
    graph = EvidenceGraph()
    add_event(graph, "event:policy-a", "Policy start")
    add_event(graph, "event:policy-b", "Policy response")
    graph.add_edge("event:policy-a", "event:policy-b", "triggers", evidence_id="ev-1")
    add_evidence(graph, "event:policy-a", "ev-1", 1, "Customers")
    add_evidence(graph, "event:policy-b", "ev-2", 2, "Employees")
    backed = backtrack_evidence(graph, EventPath(("event:policy-a", "event:policy-b"), ("triggers",)))

    with_constraint = rerank_paths("policy", graph, [backed], use_stakeholder_constraint=True)[0]
    without_constraint = rerank_paths("policy", graph, [backed], use_stakeholder_constraint=False)[0]

    assert with_constraint.stakeholder_coverage > 0
    assert without_constraint.stakeholder_coverage == 0.0
    assert with_constraint.score > without_constraint.score


def test_temporal_ablation_changes_path_ranking_features() -> None:
    graph = EvidenceGraph()
    add_event(graph, "event:policy-a", "Policy start")
    add_event(graph, "event:policy-b", "Policy response")
    graph.add_edge("event:policy-a", "event:policy-b", "precedes", evidence_id="ev-1")
    add_evidence(graph, "event:policy-a", "ev-1", 1, "Customers")
    add_evidence(graph, "event:policy-b", "ev-2", 2, "Employees")
    backed = backtrack_evidence(graph, EventPath(("event:policy-a", "event:policy-b"), ("precedes",)))

    with_temporal = rerank_paths("policy", graph, [backed], use_temporal_information=True)[0]
    without_temporal = rerank_paths("policy", graph, [backed], use_temporal_information=False)[0]

    assert with_temporal.temporal_coherence == 1.0
    assert without_temporal.temporal_coherence == 0.0
    assert with_temporal.score > without_temporal.score
