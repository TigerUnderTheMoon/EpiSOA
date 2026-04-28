import json
from pathlib import Path

from episoa.evaluation.evaluator import evaluate
from episoa.evaluation.faithfulness_metrics import evaluate_jsonl, support_rate, unsupported_tuple_rate
from episoa.evaluation.path_metrics import path_recall_at_k
from episoa.evaluation.retrieval_metrics import evidence_recall_at_k
from episoa.evaluation.tuple_metrics import (
    sentiment_accuracy,
    stakeholder_f1,
    stakeholder_precision,
    stakeholder_recall,
    tuple_level_f1,
)


def prediction_rows() -> list[dict]:
    return [
        {
            "event": "Policy change",
            "stakeholder": "Customers",
            "opinion": "Customers opposed the change.",
            "sentiment": "negative",
            "rationale": "Supported by public comments.",
            "event_chain": ["proposal", "public comments", "policy change"],
            "evidence_ids": ["ev-1"],
            "support_score": 0.9,
            "verified": True,
        },
        {
            "event": "Policy change",
            "stakeholder": "Agency",
            "opinion": "Agency revised the policy.",
            "sentiment": "neutral",
            "rationale": "Official statement.",
            "event_chain": ["public comments", "agency review", "policy revision"],
            "evidence_ids": ["ev-2"],
            "support_score": 0.6,
            "verified": False,
        },
    ]


def gold_rows() -> list[dict]:
    return [
        {
            "event": "Policy change",
            "stakeholder": "Customers",
            "opinion": "Customers opposed the change.",
            "sentiment": "negative",
            "rationale": "Supported by public comments.",
            "event_chain": ["proposal", "public comments", "policy change"],
            "evidence_ids": ["ev-1"],
            "support_score": 1.0,
            "verified": True,
        },
        {
            "event": "Policy change",
            "stakeholder": "Businesses",
            "opinion": "Businesses requested a delay.",
            "sentiment": "negative",
            "rationale": "Business association comment.",
            "event_chain": ["proposal", "business feedback", "policy revision"],
            "evidence_ids": ["ev-3"],
            "support_score": 1.0,
            "verified": True,
        },
    ]


def gold_event_chain_rows() -> list[dict]:
    return [
        {
            "target_event": "Policy change",
            "event_chain": ["proposal", "public comments", "policy change"],
            "relation_types": ["precedes", "triggers"],
            "evidence_ids": ["ev-1"],
        },
        {
            "target_event": "Policy revision",
            "event_chain": ["proposal", "business feedback", "policy revision"],
            "relation_types": ["precedes", "triggers"],
            "evidence_ids": ["ev-3"],
        },
    ]


def test_stakeholder_precision() -> None:
    assert stakeholder_precision(prediction_rows(), gold_rows()) == 0.5


def test_stakeholder_recall() -> None:
    assert stakeholder_recall(prediction_rows(), gold_rows()) == 0.5


def test_stakeholder_f1() -> None:
    assert stakeholder_f1(prediction_rows(), gold_rows()) == 0.5


def test_sentiment_accuracy() -> None:
    assert sentiment_accuracy(prediction_rows(), gold_rows()) == 1.0


def test_tuple_level_f1() -> None:
    assert tuple_level_f1(prediction_rows(), gold_rows()) == 0.5


def test_evidence_recall_at_k() -> None:
    assert evidence_recall_at_k(prediction_rows(), gold_rows(), k=2) == 0.5


def test_evidence_recall_at_1_3_5() -> None:
    assert evidence_recall_at_k(prediction_rows(), gold_rows(), k=1) == 0.5
    assert evidence_recall_at_k(prediction_rows(), gold_rows(), k=3) == 0.5
    assert evidence_recall_at_k(prediction_rows(), gold_rows(), k=5) == 0.5


def test_path_recall_at_k() -> None:
    assert path_recall_at_k(prediction_rows(), gold_event_chain_rows(), k=2) == 0.5


def test_path_recall_at_1_3_5() -> None:
    assert path_recall_at_k(prediction_rows(), gold_event_chain_rows(), k=1) == 0.5
    assert path_recall_at_k(prediction_rows(), gold_event_chain_rows(), k=3) == 0.5
    assert path_recall_at_k(prediction_rows(), gold_event_chain_rows(), k=5) == 0.5


def test_support_rate() -> None:
    assert support_rate(prediction_rows(), gold_rows()) == 0.5


def test_unsupported_tuple_rate() -> None:
    assert unsupported_tuple_rate(prediction_rows(), gold_rows()) == 0.5


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")


def test_evaluate_jsonl_writes_metrics_json() -> None:
    suffix = "evaluation_metrics"
    prediction_path = Path(f"outputs/{suffix}_predictions.jsonl")
    gold_path = Path(f"outputs/{suffix}_gold.jsonl")
    metrics_path = Path(f"outputs/{suffix}_metrics.json")
    write_jsonl(prediction_path, prediction_rows())
    write_jsonl(gold_path, gold_rows())

    metrics = evaluate_jsonl(prediction_path, gold_path, metrics_path, k=2)

    assert metrics_path.exists()
    loaded = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert loaded == metrics
    assert loaded["stakeholder_f1"] == 0.5
    assert loaded["unsupported_tuple_rate"] == 0.5


def test_unified_evaluator_writes_metrics_json_and_summary_table() -> None:
    suffix = "unified_evaluator"
    prediction_path = Path(f"outputs/{suffix}_predictions.jsonl")
    gold_tuple_path = Path(f"outputs/{suffix}_gold_tuples.jsonl")
    gold_chain_path = Path(f"outputs/{suffix}_gold_chains.jsonl")
    metrics_path = Path(f"outputs/{suffix}_metrics.json")
    summary_path = Path(f"outputs/{suffix}_summary_table.csv")
    write_jsonl(prediction_path, prediction_rows())
    write_jsonl(gold_tuple_path, gold_rows())
    write_jsonl(gold_chain_path, gold_event_chain_rows())

    metrics = evaluate(
        prediction_path,
        gold_tuple_path,
        gold_chain_path,
        metrics_path=metrics_path,
        summary_table_path=summary_path,
    )

    assert metrics_path.exists()
    assert summary_path.exists()
    assert metrics["stakeholder_precision"] == 0.5
    assert metrics["stakeholder_recall"] == 0.5
    assert metrics["evidence_recall_at_1"] == 0.5
    assert metrics["evidence_recall_at_3"] == 0.5
    assert metrics["evidence_recall_at_5"] == 0.5
    assert metrics["path_recall_at_1"] == 0.5
    assert metrics["path_recall_at_3"] == 0.5
    assert metrics["path_recall_at_5"] == 0.5
    assert metrics["support_rate"] == 0.5
    assert "summary_table" in summary_path.name
