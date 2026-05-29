import csv

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.benchmark_metrics import eval_tuple_identification
from episoa.evaluation.evaluate_main import evaluate_main
from episoa.evaluation.metrics import (
    match_tuples,
    semantic_tuple_f1,
    soft_tuple_f1,
    stakeholder_recall,
    tuple_f1,
    tuple_match_threshold_sweep,
)
from episoa.pipeline import _write_event_level_csv


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


def test_semantic_tuple_f1_is_same_event_one_to_one() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="公众与网友",
            opinion="关注事件并表达担忧",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]
    predictions = [
        PredictionTuple(
            event_id="evt-1",
            stakeholder="网友",
            opinion="关注事件并表达担忧",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        ),
        PredictionTuple(
            event_id="evt-2",
            stakeholder="公众与网友",
            opinion="关注事件并表达担忧",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-2"],
            support_label="supported",
        ),
    ]

    metrics = semantic_tuple_f1(gold, predictions, threshold=0.5)

    assert metrics["true_positives"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 1.0


def test_threshold_sweep_reports_semantic_audit_metric() -> None:
    rows = tuple_match_threshold_sweep([], [])

    assert any(row["matcher"] == "semantic" for row in rows)


def test_soft_tuple_f1_uses_one_to_one_matching() -> None:
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
            support_label="supported",
        ),
        PredictionTuple(
            event_id="evt-1",
            stakeholder="Residents",
            opinion="Oppose the plan",
            sentiment="negative",
            rationale="Duplicate",
            evidence_ids=["ev-2"],
            support_label="supported",
        ),
    ]

    soft = soft_tuple_f1(gold, predictions)
    match_result = match_tuples(gold, predictions)

    assert soft["true_positives"] == 1
    assert soft["precision"] == 0.5
    assert soft["recall"] == 1.0
    assert soft["f1"] == 0.6667
    assert len(match_result["matches"]) == 1


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


def test_evaluate_main_excludes_predictions_without_gold_event_from_f1() -> None:
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
            support_label="supported",
            verified=True,
        ),
        PredictionTuple(
            event_id="evt-2",
            stakeholder="Other stakeholder",
            opinion="Unscored smoke-only prediction",
            sentiment="neutral",
            rationale="Rationale",
            evidence_ids=["ev-2"],
            support_label="supported",
            verified=True,
        ),
    ]

    metrics = evaluate_main(gold, predictions)

    assert metrics["Metric-Scope"] == "gold_event_scope"
    assert metrics["Tuple-F1-soft"] == 1.0
    assert metrics["Num-Tuples"] == 1
    assert metrics["Num-Tuples-All"] == 2
    assert metrics["Excluded-Predictions"] == 1
    assert metrics["Excluded-Event-Ids"] == "evt-2"


def test_event_level_csv_excludes_predictions_without_gold_event(tmp_path) -> None:
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
            support_label="supported",
        ),
        PredictionTuple(
            event_id="evt-2",
            stakeholder="Other",
            opinion="Smoke-only tuple",
            sentiment="neutral",
            rationale="Rationale",
            evidence_ids=["ev-2"],
            support_label="supported",
        ),
    ]
    path = tmp_path / "event_level_metrics.csv"

    _write_event_level_csv(path, gold, predictions)

    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    assert [row["event_id"] for row in rows] == ["evt-1"]
    assert rows[0]["num_pred"] == "1"


def test_benchmark_tuple_eval_uses_shared_one_to_one_matcher() -> None:
    predictions = [
        {
            "event_id": "evt-1",
            "output": {
                "gold_tuples": [
                    {"stakeholder": "Residents", "opinion": "Oppose the plan", "sentiment": "negative"}
                ]
            },
            "prediction": {
                "tuples": [
                    {"stakeholder": "Residents", "opinion": "Oppose the plan", "sentiment": "negative"},
                    {"stakeholder": "Residents", "opinion": "Oppose the plan", "sentiment": "negative"},
                ]
            },
        }
    ]

    metrics = eval_tuple_identification(predictions)

    assert metrics["metric_scope"] == "formal"
    assert metrics["true_positives_soft"] == 1
    assert metrics["stakeholder_opinion_f1_soft"] == 0.6667


def test_benchmark_tuple_eval_marks_zero_gold_as_smoke_only() -> None:
    predictions = [
        {
            "event_id": "evt-1",
            "output": {"gold_tuples": []},
            "prediction": {
                "tuples": [
                    {"stakeholder": "Residents", "opinion": "Generated smoke tuple", "sentiment": "neutral"}
                ]
            },
        }
    ]

    metrics = eval_tuple_identification(predictions)

    assert metrics["metric_scope"] == "smoke_only"
    assert metrics["gold_tuples"] == 0
    assert metrics["pred_tuples"] == 1
