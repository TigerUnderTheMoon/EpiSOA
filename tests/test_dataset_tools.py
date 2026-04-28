import csv
import importlib.util
import json
from pathlib import Path


def load_script(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_validate_dataset_flags_mock_markers(tmp_path: Path) -> None:
    module = load_script("scripts/validate_dataset.py", "validate_dataset")
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "gold_tuples.jsonl"
    chains = tmp_path / "gold_event_chains.jsonl"

    write_jsonl(events, [{"event_id": "evt-1", "target_event": "Real event", "event_chain": ["a"]}])
    write_jsonl(
        evidence,
        [{"evidence_id": "ev-1", "event_id": "evt-1", "url": "https://example.org/item", "text": "text"}],
    )
    write_jsonl(
        tuples,
        [
            {
                "event_id": "evt-1",
                "stakeholder": "group",
                "opinion": "opinion",
                "sentiment": "neutral",
                "rationale": "rationale",
                "event_chain": ["a"],
                "evidence_ids": ["ev-1"],
                "support_score": 0.9,
                "verified": True,
            }
        ],
    )
    write_jsonl(chains, [{"event_id": "evt-1", "event_chain": ["a"]}])

    report = module.validate_dataset(events, evidence, tuples, chains)

    assert report["errors"] == []
    assert report["is_formal_dataset"] is False
    assert any("example.org" in warning for warning in report["warnings"])


def test_build_annotation_sheet_headers_for_empty_formal(tmp_path: Path) -> None:
    module = load_script("scripts/build_annotation_sheet.py", "build_annotation_sheet")
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    output = tmp_path / "annotation.csv"
    events.write_text("", encoding="utf-8")
    evidence.write_text("", encoding="utf-8")

    assert module.write_annotation_sheet(events, evidence, output) == 0

    with output.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader)
    assert headers == module.FIELDNAMES


def test_convert_annotation_csv_to_gold_and_validate(tmp_path: Path) -> None:
    validate_module = load_script("scripts/validate_dataset.py", "validate_dataset_for_convert_test")
    convert_module = load_script("scripts/convert_annotation_csv_to_gold.py", "convert_annotation_csv_to_gold")
    assert validate_module is not None
    dataset_dir = tmp_path / "dataset"
    write_jsonl(dataset_dir / "events.jsonl", [{"event_id": "evt-1", "target_event": "Event", "event_chain": ["a"]}])
    write_jsonl(dataset_dir / "evidence.jsonl", [{"evidence_id": "ev-1", "event_id": "evt-1", "text": "real text"}])
    write_jsonl(dataset_dir / "gold_event_chains.jsonl", [{"event_id": "evt-1", "event_chain": ["a"]}])
    csv_path = tmp_path / "filled.csv"
    csv_path.write_text(
        "event_id,evidence_id,platform,url,timestamp,source_type,text,suggested_stakeholder,"
        "suggested_sentiment,annotated_stakeholder,annotated_opinion,annotated_sentiment,"
        "annotated_rationale,annotated_event_chain,annotated_evidence_ids,support_score,verified,notes\n"
        "evt-1,ev-1,,,,,,,"
        ",residents,opinion,positive,rationale,a,ev-1,0.75,true,\n",
        encoding="utf-8",
    )

    output = dataset_dir / "gold_tuples.jsonl"
    assert convert_module.convert_csv_to_gold(csv_path, output) == 1
    report = validate_module.validate_dataset(
        dataset_dir / "events.jsonl",
        dataset_dir / "evidence.jsonl",
        output,
        dataset_dir / "gold_event_chains.jsonl",
    )

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert records[0]["tuple_id"] == "tuple-00001"
    assert records[0]["event_chain"] == ["a"]
    assert records[0]["evidence_ids"] == ["ev-1"]
    assert report["is_formal_dataset"] is True
