from episoa.pipeline import paper_status


def test_paper_status_reports_empty_dataset_blocked() -> None:
    status = paper_status()

    assert status["paper_readiness"]["data_ready"] is False
    assert status["paper_readiness"]["formal_events_ready"] is False
    assert status["dataset"]["num_gold_tuples"] == 0
    assert status["dataset"]["num_evidence"] == 0
    assert status["next_commands"]
