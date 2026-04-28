from datetime import datetime, timezone

from episoa.baselines import direct_llm, diversity_rag, episoa_full, graph_retrieval, vanilla_rag
from episoa.experiment import configure_logging, create_run_context
from episoa.schemas.attribution import AttributionTuple
from episoa.schemas.evidence import EvidenceRecord


class PoisonEvidencePool:
    def __iter__(self):
        raise AssertionError("direct_llm must not access evidence_pool")

    def __len__(self):
        raise AssertionError("direct_llm must not access evidence_pool")

    def __getitem__(self, index):
        raise AssertionError("direct_llm must not access evidence_pool")


def make_evidence(evidence_id: str, stakeholder: str, sentiment: str, day: int) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        platform="Example",
        url=f"https://example.com/{evidence_id}",
        timestamp=datetime(2026, 4, day, tzinfo=timezone.utc),
        text=f"{stakeholder} expressed {sentiment} views about the policy change.",
        author_alias=stakeholder,
        source_type="news",
        metadata={
            "event": "Policy change",
            "stakeholder": stakeholder,
            "sentiment": sentiment,
            "stance": sentiment,
            "opinion": f"{stakeholder} expressed {sentiment} views.",
        },
    )


def evidence_pool() -> list[EvidenceRecord]:
    return [
        make_evidence("ev-1", "Customers", "negative", 1),
        make_evidence("ev-2", "Agency", "neutral", 2),
        make_evidence("ev-3", "Businesses", "mixed", 3),
    ]


def assert_attribution_schema(rows: list[AttributionTuple]) -> None:
    assert rows
    for row in rows:
        AttributionTuple.model_validate(row.model_dump())
        assert row.evidence


def test_direct_llm_uses_unified_interface_without_evidence_pool_access() -> None:
    rows = direct_llm.run("Policy change", PoisonEvidencePool(), {})

    assert_attribution_schema(rows)
    assert rows[0].evidence[0].metadata["uses_evidence_pool"] is False


def test_vanilla_rag_uses_relevance_only_retrieval() -> None:
    rows = vanilla_rag.run("policy change customers", evidence_pool(), {"top_k": 2})

    assert_attribution_schema(rows)
    assert {item.evidence_id for row in rows for item in row.evidence}.issubset({"ev-1", "ev-2", "ev-3"})


def test_diversity_rag_runs_with_diversity_retriever() -> None:
    rows = diversity_rag.run("policy change", evidence_pool(), {"top_k": 3})

    assert_attribution_schema(rows)
    assert len({row.stakeholder for row in rows}) >= 2


def test_graph_retrieval_uses_graph_without_eventrag_retriever() -> None:
    assert not hasattr(graph_retrieval, "retrieve_event_chains")

    rows = graph_retrieval.run("policy change", evidence_pool(), {"top_k": 2})

    assert_attribution_schema(rows)


def test_episoa_full_runs_complete_pipeline() -> None:
    run_context = create_run_context("baseline-episoa-full-test")
    configure_logging(run_context.log_path)

    rows = episoa_full.run(
        {"target_event": "Policy change", "time_window": {"start": "2026-04-01", "end": "2026-04-30"}},
        evidence_pool(),
        {
            "pipeline": {"top_k_evidence": 3, "eventrag_depth": 2, "eventrag_top_k": 1},
            "llm": {"mode": "mock"},
            "run_context": run_context,
        },
    )

    assert_attribution_schema(rows)
    assert run_context.predictions_path.exists()
