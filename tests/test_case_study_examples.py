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


def test_export_paper_tables_writes_spec_outputs(tmp_path: Path) -> None:
    module_path = Path("scripts/export_paper_tables.py")
    spec = importlib.util.spec_from_file_location("export_paper_tables", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    run_dir = tmp_path / "runs" / "paper-run"
    baseline_dir = run_dir / "baselines" / "vanilla_rag"
    ablation_dir = run_dir / "ablations" / "without_verifier"
    baseline_dir.mkdir(parents=True)
    ablation_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    metrics = {"tuple_f1": 0.5, "stakeholder_f1": 0.6, "opinion_f1": 0.7}
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (baseline_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (ablation_dir / "metrics.json").write_text(json.dumps({**metrics, "path_recall_at_k": 0.4}), encoding="utf-8")
    (run_dir / "case_study_examples.json").write_text(
        json.dumps({"cases": [{"case_id": "case-1", "case_type": "representative", "source": "predictions.jsonl"}]}),
        encoding="utf-8",
    )

    paths = module.export_paper_tables(tmp_path / "runs", tmp_path / "results")

    assert paths["main_results"].name == "main_results.csv"
    assert paths["ablation_results"].name == "ablation_results.csv"
    assert paths["case_studies"].name == "case_studies.jsonl"
    assert "Vanilla RAG" in paths["main_results"].read_text(encoding="utf-8")
    assert "w/o verifier" in paths["ablation_results"].read_text(encoding="utf-8")
    assert "case-1" in paths["case_studies"].read_text(encoding="utf-8")
