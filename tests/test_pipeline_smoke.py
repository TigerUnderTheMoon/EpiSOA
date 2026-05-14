from episoa.pipeline import paper_status


def test_paper_status_returns_valid_structure() -> None:
    status = paper_status()

    assert "paper_readiness" in status
    assert isinstance(status["paper_readiness"]["data_ready"], bool)
    assert isinstance(status["paper_readiness"]["events_ready"], bool)
    assert "dataset" in status
    assert "num_gold_tuples" in status["dataset"]
    assert status["next_commands"] is not None
