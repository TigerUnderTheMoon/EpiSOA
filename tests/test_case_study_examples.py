import importlib.util
import json
from pathlib import Path


def load_case_study_module():
    module_path = Path("scripts/case_study_examples.py")
    spec = importlib.util.spec_from_file_location("case_study_examples", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_validate_outputs_module():
    module_path = Path("scripts/validate_outputs.py")
    spec = importlib.util.spec_from_file_location("validate_outputs", module_path)
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


def test_case_study_examples_and_validation_outputs_shape() -> None:
    case_study = load_case_study_module()
    validate_outputs = load_validate_outputs_module()
    run_dir = Path("outputs/test_case_study_run")
    prediction_path = run_dir / "predictions" / "method.jsonl"
    gold_path = run_dir / "gold_tuples.jsonl"
    write_jsonl(
        prediction_path,
        [
            {
                "event": "Policy change",
                "stakeholder": "Customers",
                "opinion": "Customers opposed the policy.",
                "sentiment": "negative",
                "rationale": "Supported by comments.",
                "event_chain": ["proposal", "comments"],
                "evidence": [
                    {
                        "evidence_id": "ev-1",
                        "text": "Customers opposed the policy.",
                    }
                ],
                "support_score": 0.9,
                "verified": True,
            }
        ],
    )
    write_jsonl(
        gold_path,
        [
            {
                "event": "Policy change",
                "stakeholder": "Customers",
                "sentiment": "negative",
                "event_chain": ["proposal", "comments"],
                "evidence_ids": ["ev-1"],
            }
        ],
    )
    for name in ["summary_table.csv", "ablation_summary.csv"]:
        (run_dir / name).write_text("header\n", encoding="utf-8")
    (run_dir / "error_analysis.jsonl").write_text("", encoding="utf-8")

    output_path = case_study.write_case_study_examples(run_dir, gold_tuples_path=gold_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["num_cases"] == 1
    assert set(payload["cases"][0]) >= {
        "case_id",
        "case_type",
        "input_text",
        "gold_label",
        "prediction",
        "analysis",
        "source",
    }
    assert validate_outputs.validate_run_outputs(run_dir)["case_study_examples.json"] is True
