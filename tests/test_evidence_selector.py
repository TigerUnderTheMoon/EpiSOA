from episoa.retrieval.evidence_selector import select_evidence_for_prompt


def test_chain_aware_selector_records_scores_and_stage_coverage():
    result = select_evidence_for_prompt(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[
            evidence_row("ev-conflict", source_type="forum", text="Residents complain about safety issue"),
            evidence_row("ev-response", source_type="official", text="Agency responds to safety issue"),
            evidence_row("ev-background", source_type="public_web", quality_score=0.99, text="Generic background"),
        ],
        max_evidence=2,
        mode="chain_aware",
    )

    ids = [row["evidence_id"] for row in result.evidence]
    assert ids == ["ev-conflict", "ev-response"]
    assert result.diagnostics["selector_mode"] == "chain_aware"
    assert result.diagnostics["stage_coverage"] > 0
    assert "selection_components" in result.evidence[0]


def test_quality_and_random_modes_are_auditable_and_deterministic():
    rows = [evidence_row("ev-low", quality_score=0.1), evidence_row("ev-high", quality_score=0.9)]

    quality = select_evidence_for_prompt(
        event=event_row(), chain={}, evidence_rows=rows, max_evidence=1, mode="quality_topk"
    )
    random_a = select_evidence_for_prompt(
        event=event_row(), chain={}, evidence_rows=rows, max_evidence=2, mode="random", seed=7
    )
    random_b = select_evidence_for_prompt(
        event=event_row(), chain={}, evidence_rows=rows, max_evidence=2, mode="random", seed=7
    )

    assert quality.evidence[0]["evidence_id"] == "ev-high"
    assert [row["evidence_id"] for row in random_a.evidence] == [row["evidence_id"] for row in random_b.evidence]
    assert random_a.diagnostics["selector_mode"] == "random"


def test_oracle_mode_forces_only_evidence_ids_not_gold_text():
    result = select_evidence_for_prompt(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[evidence_row("ev-conflict"), evidence_row("ev-response")],
        max_evidence=2,
        mode="oracle",
        oracle_evidence_ids=["ev-response"],
    )

    assert result.evidence[0]["evidence_id"] == "ev-response"
    assert result.diagnostics["oracle_gold_evidence_ids"] == ["ev-response"]
    assert "gold_tuple" not in str(result.diagnostics).lower()


def test_stakeholder_candidates_are_prioritized_before_selector_fill():
    result = select_evidence_for_prompt(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[
            evidence_row("ev-residents", quality_score=0.4, text="Residents complain about safety"),
            evidence_row("ev-agency", quality_score=0.3, text="Agency responds to safety issue"),
            evidence_row("ev-high", quality_score=0.99, text="Generic background about safety"),
        ],
        max_evidence=2,
        mode="quality_topk",
        stakeholder_candidates=["Residents", "Agency"],
    )

    assert [row["evidence_id"] for row in result.evidence] == ["ev-residents", "ev-agency"]
    assert result.diagnostics["covered_stakeholder_candidates"] == ["Agency", "Residents"]
    assert result.diagnostics["stakeholder_candidate_coverage"] == 1.0
    assert result.evidence[0]["unmatched_candidate_allowed"] is False


def test_selector_marks_unmatched_candidate_allowed_for_non_candidate_evidence():
    result = select_evidence_for_prompt(
        event=event_row(),
        chain={},
        evidence_rows=[evidence_row("ev-public", quality_score=0.99, text="Public background without named candidate")],
        max_evidence=1,
        mode="quality_topk",
        stakeholder_candidates=["Residents"],
    )

    assert result.evidence[0]["unmatched_candidate_allowed"] is True


def test_coverage_optimized_covers_stage_source_stakeholder_and_avoids_duplicate():
    result = select_evidence_for_prompt(
        event=event_row(),
        chain=chain_row(),
        evidence_rows=[
            evidence_row("ev-conflict", source_type="forum", quality_score=0.9, text="Residents complain about safety issue"),
            evidence_row("ev-duplicate", source_type="forum", quality_score=0.89, text="Residents complain about safety issue"),
            evidence_row("ev-response", source_type="official", quality_score=0.7, text="Agency responds to safety issue"),
            evidence_row("ev-resolution", source_type="news", quality_score=0.7, text="Agency resolution plan addresses safety"),
        ],
        max_evidence=3,
        mode="coverage_optimized",
        stakeholder_candidates=["Residents", "Agency"],
    )

    ids = [row["evidence_id"] for row in result.evidence]
    assert result.diagnostics["selector_mode"] == "coverage_optimized"
    assert "ev-duplicate" not in ids
    assert {"Residents", "Agency"} <= set(result.diagnostics["covered_stakeholder_candidates"])
    assert "coverage_objective_components" in result.diagnostics
    assert "source_type_distribution" in result.diagnostics


def event_row():
    return {
        "event_id": "E1",
        "event_name": "Safety dispute",
        "event_description": "Residents complain and agency responds",
        "seed_keywords": ["safety", "residents"],
        "stakeholder_hints": ["Residents", "Agency"],
        "stance_hints": ["complain", "responds"],
    }


def evidence_row(evidence_id, *, source_type="news", quality_score=0.5, text="Residents complain about safety"):
    return {
        "event_id": "E1",
        "evidence_id": evidence_id,
        "source_type": source_type,
        "source": source_type,
        "title": text,
        "text": text,
        "quality_score": quality_score,
    }


def chain_row():
    return {
        "event_id": "E1",
        "stages": [
            {
                "stage": "conflict",
                "evidence": [{"evidence_id": "ev-conflict", "final_stage_score": 0.9, "event_relevance_score": 0.9}],
            },
            {
                "stage": "response",
                "evidence": [{"evidence_id": "ev-response", "final_stage_score": 0.8, "event_relevance_score": 0.8}],
            },
        ],
    }
