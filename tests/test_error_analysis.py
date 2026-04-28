import csv
import importlib.util
import json
from pathlib import Path


def load_error_analysis_module():
    module_path = Path("scripts/error_analysis.py")
    spec = importlib.util.spec_from_file_location("error_analysis", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_error_analysis_writes_paper_ready_csv_and_jsonl() -> None:
    error_analysis = load_error_analysis_module()
    run_dir = Path("outputs/test_error_analysis_run")
    prediction_path = run_dir / "predictions" / "method.jsonl"
    gold_tuple_path = run_dir / "gold_tuples.jsonl"
    gold_chain_path = run_dir / "gold_event_chains.jsonl"

    prediction = {
        "event": "Policy change",
        "stakeholder": "Customers",
        "opinion": "Customers supported the policy.",
        "sentiment": "positive",
        "rationale": "Supported by comments.",
        "event_chain": ["proposal", "policy change"],
        "evidence_ids": ["ev-x"],
        "support_score": 0.4,
        "verified": True,
    }
    gold = {
        "event": "Policy change",
        "stakeholder": "Customers",
        "opinion": "Customers opposed the policy.",
        "sentiment": "negative",
        "rationale": "Public comments opposed it.",
        "event_chain": ["proposal", "public comments", "policy change"],
        "evidence_ids": ["ev-1"],
        "support_score": 1.0,
        "verified": True,
    }
    write_jsonl(prediction_path, [prediction])
    write_jsonl(gold_tuple_path, [gold])
    write_jsonl(gold_chain_path, [{"target_event": "Policy change", "event_chain": gold["event_chain"]}])

    rows = error_analysis.analyze_run(run_dir, gold_tuples_path=gold_tuple_path, gold_event_chains_path=gold_chain_path)
    csv_path, jsonl_path = error_analysis.write_error_analysis(rows, run_dir)

    assert csv_path.exists()
    assert jsonl_path.exists()
    assert {row["error_type"] for row in rows} >= {
        "wrong_sentiment",
        "missing_evidence",
        "unsupported_rationale",
        "wrong_event_chain",
    }
    with csv_path.open("r", encoding="utf-8", newline="") as file:
        csv_rows = list(csv.DictReader(file))
    assert csv_rows
    assert "method" in csv_rows[0]
    assert "error_type" in csv_rows[0]
