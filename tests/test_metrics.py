from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.metrics import tuple_f1


def test_tuple_f1_matches_identical_tuple() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="Residents",
            opinion="Opinion",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]
    predictions = [
        PredictionTuple(
            event_id="evt-1",
            stakeholder="Residents",
            opinion="Opinion",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]

    assert tuple_f1(gold, predictions) == 1.0
