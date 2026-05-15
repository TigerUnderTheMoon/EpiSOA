from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.evaluate_main import evaluate_main
from episoa.evaluation.metrics import soft_tuple_f1, stakeholder_recall, tuple_f1


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


def test_soft_tuple_f1_does_not_match_across_events() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="Residents",
            opinion="Oppose the plan",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]
    predictions = [
        PredictionTuple(
            event_id="evt-2",
            stakeholder="Residents",
            opinion="Oppose the plan",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-2"],
            support_label="supported",
        )
    ]

    soft = soft_tuple_f1(gold, predictions)

    assert soft["true_positives"] == 0
    assert soft["precision"] == 0.0
    assert soft["recall"] == 0.0
    assert soft["f1"] == 0.0


def test_stakeholder_recall_does_not_match_across_events() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="Residents",
            opinion="Oppose the plan",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]
    predictions = [
        PredictionTuple(
            event_id="evt-2",
            stakeholder="Residents",
            opinion="Different opinion",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-2"],
            support_label="supported",
        )
    ]

    assert stakeholder_recall(gold, predictions) == 0.0


def test_evaluate_main_labels_candidate_utr_when_verifier_disabled() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="Residents",
            opinion="Oppose the plan",
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
            opinion="Oppose the plan",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="insufficient_evidence",
            verified=False,
        )
    ]

    metrics = evaluate_main(gold, predictions, verifier_enabled=False)

    assert metrics["ESR"] is None
    assert metrics["UTR"] is None
    assert metrics["Candidate-UTR"] == 1.0
