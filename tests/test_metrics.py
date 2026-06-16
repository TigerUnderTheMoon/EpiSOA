import csv

from episoa.data.schema import GoldTuple, PredictionTuple
from episoa.evaluation.benchmark_metrics import eval_tuple_identification, eval_tuple_identification_llm_judge
from episoa.evaluation.evaluate_main import evaluate_main
from episoa.evaluation.metrics import (
    match_tuples,
    semantic_tuple_f1,
    soft_tuple_f1,
    stakeholder_recall,
    tuple_f1,
    tuple_match_threshold_sweep,
)
from episoa.pipeline import _write_event_level_csv, _write_scoring_artifacts


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


def test_match_tuples_prefers_maximum_cardinality_before_score() -> None:
    gold = [
        {"event_id": "evt-1", "stakeholder": "ABCD", "opinion": "same", "sentiment": "neutral"},
        {"event_id": "evt-1", "stakeholder": "CDEF", "opinion": "same", "sentiment": "neutral"},
    ]
    predictions = [
        {"event_id": "evt-1", "stakeholder": "ABCDE", "opinion": "same", "sentiment": "neutral"},
        {"event_id": "evt-1", "stakeholder": "ABC", "opinion": "same", "sentiment": "neutral"},
    ]

    result = match_tuples(
        gold,
        predictions,
        matcher="char_jaccard",
        threshold=0.5,
        field_weights={"stakeholder": 1.0},
    )

    assert result["matching_strategy"] == "max_cardinality_max_score"
    assert len(result["matches"]) == 2
    assert result["matched_gold_indices"] == [0, 1]
    assert result["matched_pred_indices"] == [0, 1]


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


def test_evaluate_main_paper_semantic_metric_is_normalized_05_with_loose_audit() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="Local residents",
            opinion="aaaaaa",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]
    predictions = [
        PredictionTuple(
            event_id="evt-1",
            stakeholder="Local residents",
            opinion="bbbbbb",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]

    metrics = evaluate_main(gold, predictions)

    assert metrics["Tuple-F1-semantic"] == metrics["Tuple-F1-semantic@0.5"]
    assert metrics["Tuple-Precision-semantic"] == metrics["Tuple-Precision-semantic@0.5"]
    assert metrics["Tuple-Recall-semantic"] == metrics["Tuple-Recall-semantic@0.5"]
    assert metrics["Tuple-F1-semantic@0.25"] == 1.0
    assert metrics["Tuple-F1-semantic@0.5"] == 0.0
    assert metrics["Tuple-F1-semantic-raw@0.5"] == 0.0
    assert metrics["Tuple-F1-char@0.5"] == metrics["Tuple-F1-soft"]
    assert "Tuple-F1-exact" in metrics
    assert "Tuple-F1-strict-char@0.5" not in metrics
    assert metrics["Stakeholder-Recall"] == metrics["Stakeholder-Recall-semantic@0.5"]
    assert metrics["Opinion-Recall"] == metrics["Opinion-Recall-semantic@0.5"]
    assert metrics["Stakeholder-Recall-char@0.5"] == 1.0
    assert metrics["Opinion-Recall-char@0.5"] == 0.0


def test_evaluate_main_sentiment_acc_uses_main_semantic_matched_pairs() -> None:
    gold = [
        GoldTuple(
            event_id="evt-1",
            stakeholder="abc",
            opinion="abc",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]
    predictions = [
        PredictionTuple(
            event_id="evt-1",
            stakeholder="abcdefghijklmnopqrstuvwxyz",
            opinion="abcdefghijklmnopqrstuvwxyz",
            sentiment="negative",
            rationale="Rationale",
            evidence_ids=["ev-1"],
            support_label="supported",
        )
    ]

    metrics = evaluate_main(gold, predictions)

    assert metrics["Tuple-F1-soft"] == 0.0
    assert metrics["Tuple-F1-semantic@0.5"] == 1.0
    assert metrics["Sentiment-Acc"] == 1.0


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


def test_tuple_failure_audit_is_aggregated_not_row_level_diagnostics(tmp_path) -> None:
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
            stakeholder="Officials",
            opinion="Explain the plan",
            sentiment="neutral",
            rationale="Rationale",
            evidence_ids=["ev-2"],
            support_label="supported",
        )
    ]

    _write_scoring_artifacts(tmp_path, gold, predictions)

    with (tmp_path / "tuple_match_diagnostics.csv").open(encoding="utf-8", newline="") as handle:
        diagnostics_rows = list(csv.DictReader(handle))
    with (tmp_path / "tuple_failure_audit.csv").open(encoding="utf-8", newline="") as handle:
        audit_reader = csv.DictReader(handle)
        audit_rows = list(audit_reader)

    assert "row_type" in diagnostics_rows[0]
    assert audit_reader.fieldnames == ["failure_reason", "count"]
    assert audit_rows == [
        {"failure_reason": "stakeholder_mismatch", "count": "1"},
        {"failure_reason": "unmatched_prediction", "count": "1"},
    ]


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


def test_benchmark_llm_judge_sentiment_accuracy_uses_matched_denominator() -> None:
    predictions = [
        {
            "event_id": "evt-1",
            "output": {
                "gold_tuples": [
                    {"stakeholder": "Residents", "opinion": "Oppose the plan", "sentiment": "negative"},
                    {"stakeholder": "Officials", "opinion": "Explain the plan", "sentiment": "neutral"},
                ]
            },
            "prediction": {
                "tuples": [
                    {"stakeholder": "Residents", "opinion": "Oppose the plan", "sentiment": "negative"},
                ]
            },
        }
    ]

    metrics = eval_tuple_identification_llm_judge(
        predictions,
        llm_client=FixedJudgeClient(
            '{"matches":[{"pred_index":0,"gold_index":0,"match":true,"reason":"same"}]}'
        ),
        model_name="fake-judge",
    )

    assert metrics["true_positives_llm_judge"] == 1
    assert metrics["sentiment_accuracy_llm_judge"] == 1.0
    assert metrics["sentiment_accuracy_gold_normalized_llm_judge"] == 0.5


class FixedJudgeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FixedJudgeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, **_kwargs) -> FixedJudgeResponse:
        return FixedJudgeResponse(self.content)
