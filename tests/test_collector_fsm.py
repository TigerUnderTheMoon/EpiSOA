from episoa.collector.fsm_graph import build_collector_graph


def run_graph(mock_coverage_scenario: str) -> dict:
    graph = build_collector_graph()
    return graph.invoke(
        {
            "target_event": "Example policy change",
            "mock_coverage_scenario": mock_coverage_scenario,
            "max_coverage_attempts": 3,
        },
        config={
            "recursion_limit": 20,
        }
    )


def test_coverage_pass_enters_stop_and_handoff() -> None:
    result = run_graph("covered")

    assert result["visited_states"][-1] == "stop_and_handoff"
    assert result["coverage_status"]["stakeholder_coverage"] == "sufficient"
    assert result["coverage_status"]["stance_diversity"] == "sufficient"
    assert result["handoff_payload"]["coverage_status"] == result["coverage_status"]


def test_stakeholder_missing_returns_to_query_planning() -> None:
    result = run_graph("stakeholder_missing")
    visited = result["visited_states"]
    first_coverage_index = visited.index("coverage_evaluation")

    assert visited[first_coverage_index + 1] == "query_planning"
    assert visited[-1] == "stop_and_handoff"
    assert result["coverage_attempts"] == 2


def test_not_enough_opinions_returns_to_search_and_page_collection() -> None:
    result = run_graph("not_enough_opinions")
    visited = result["visited_states"]
    first_coverage_index = visited.index("coverage_evaluation")

    assert visited[first_coverage_index + 1] == "search_and_page_collection"
    assert visited[-1] == "stop_and_handoff"
    assert result["coverage_attempts"] == 2


def test_semireal_search_uses_seed_pages_privacy_filter_and_limits() -> None:
    graph = build_collector_graph()
    seed_pages = [
        {
            "evidence_id": "seed-001",
            "url": "https://example.org/public/news",
            "platform": "Public News",
            "source": "news",
            "timestamp": "2026-02-01T10:00:00Z",
            "text": "Residents objected to the plan. Contact resident@example.org or 555-123-4567.",
            "author_name": "Resident Speaker",
            "author_profile_url": "https://example.org/users/resident-speaker",
            "metadata": {"stakeholder": "residents", "sentiment": "negative", "stance": "opposed"},
        },
        {
            "evidence_id": "seed-002",
            "url": "https://example.org/public/official",
            "platform": "City Updates",
            "source": "official_response",
            "timestamp": "2026-02-02T10:00:00Z",
            "text": "City engineers said they revised the plan after comments.",
            "author_name": "City Office",
            "author_profile_url": "https://example.org/users/city-office",
            "metadata": {"stakeholder": "city engineers", "sentiment": "neutral", "stance": "responsive"},
        },
        {
            "evidence_id": "seed-003",
            "url": "https://example.org/public/forum",
            "platform": "Public Forum",
            "source": "forum",
            "timestamp": "2026-02-03T10:00:00Z",
            "text": "Local shops asked for a clearer timeline.",
            "author_name": "Shop Association",
            "author_profile_url": "https://example.org/users/shop-association",
            "metadata": {"stakeholder": "small businesses", "sentiment": "mixed", "stance": "concerned"},
        },
    ]

    result = graph.invoke(
        {
            "target_event": "Riverton flood barrier plan",
            "collection_mode": "semireal_search",
            "seed_urls": seed_pages,
            "source_types": ["news", "forum", "official_response", "public_web"],
            "max_queries_per_event": 20,
            "max_pages_per_query": 20,
            "max_evidence_per_event": 2,
        },
        config={"recursion_limit": 30},
    )

    assert len(result["query_plan"]) == 8
    assert result["selected_sources"] == ["news", "forum", "official_response", "public_web"]
    assert len(result["pages"]) <= 2
    assert len(result["evidence"]) == 2
    assert result["coverage_attempts"] <= 3
    assert result["visited_states"][-1] == "stop_and_handoff"
    assert "resident@example.org" not in result["evidence"][0]["text"]
    assert "555-123-4567" not in result["evidence"][0]["text"]
    assert result["evidence"][0]["author_alias"].startswith("author_")
    assert result["evidence"][1]["source_type"] == "official"
    assert result["coverage_status"]["traceability_rate"] == 1.0


def test_semireal_feedback_transitions_stop_after_two_rounds() -> None:
    graph = build_collector_graph()

    result = graph.invoke(
        {
            "target_event": "Sparse event",
            "collection_mode": "semireal_search",
            "seed_urls": [
                {
                    "evidence_id": "seed-001",
                    "url": "https://example.org/public/news",
                    "platform": "Public News",
                    "source": "news",
                    "timestamp": "2026-02-01T10:00:00Z",
                    "text": "One stakeholder comment only.",
                    "metadata": {"stakeholder": "residents", "sentiment": "negative", "stance": "opposed"},
                }
            ],
        },
        config={"recursion_limit": 30},
    )

    assert result["coverage_attempts"] == 3
    assert result["visited_states"][-1] == "stop_and_handoff"
    assert result["coverage_status"]["stakeholder_coverage"] == "failed"
