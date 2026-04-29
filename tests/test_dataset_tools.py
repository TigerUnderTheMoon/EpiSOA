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
                "support_label": "supported",
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
        "annotated_rationale,annotated_event_chain,annotated_evidence_ids,support_label,support_score,verified,notes\n"
        "evt-1,ev-1,,,,,,,"
        ",residents,opinion,positive,rationale,a,ev-1,supported,0.75,true,\n",
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
    assert records[0]["support_label"] == "supported"
    assert report["is_formal_dataset"] is True


def test_urban_renewal_data_construction_flow(tmp_path: Path) -> None:
    dataset = load_script("src/episoa/dataset_construction.py", "dataset_construction")
    sheet_module = load_script("scripts/build_annotation_sheet.py", "build_sheet_for_flow")
    convert_module = load_script("scripts/convert_annotation_csv_to_gold.py", "convert_for_flow")
    validate_module = load_script("scripts/validate_dataset.py", "validate_for_flow")

    source_csv = tmp_path / "exports.csv"
    source_csv.write_text(
        "event_seed_id,platform,url,timestamp,source_type,title,text\n"
        "block-a,News,https://news.test/a,2026-01-01T00:00:00Z,news,旧改补偿方案公布,居民质疑旧改补偿方案不透明 contact@example.com\n"
        "block-b,Forum,https://forum.test/b,2026-01-02T00:00:00Z,forum,城市更新听证,商户担心城市更新影响经营 555-123-4567\n",
        encoding="utf-8",
    )

    raw = tmp_path / "raw_posts.jsonl"
    events = tmp_path / "events.jsonl"
    silver = tmp_path / "silver_tuples.jsonl"
    pairs = tmp_path / "candidate_evidence_pairs.jsonl"
    sheet = tmp_path / "annotation.csv"
    filled = tmp_path / "annotation_filled.csv"
    evidence = tmp_path / "evidence.jsonl"
    gold = tmp_path / "gold_tuples.jsonl"
    chains = tmp_path / "gold_event_chains.jsonl"

    dataset.import_raw_posts(source_csv, raw)
    dataset.extract_events(raw, events)
    dataset.generate_silver_tuples(raw, events, silver)
    dataset.build_evidence_pairs(raw, silver, pairs)
    sheet_module.write_annotation_sheet(events, evidence, sheet, candidate_pairs_path=pairs)

    rows = list(csv.DictReader(sheet.open("r", encoding="utf-8", newline="")))
    assert len(rows) == 2
    for row in rows:
        row["support_label"] = "supported"
        row["support_score"] = "0.85"
        row["verified"] = "true"
    with filled.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sheet_module.FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    convert_module.convert_csv_to_gold(filled, gold, evidence_output_path=evidence)
    event_records = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    write_jsonl(chains, [{"event_id": item["event_id"], "event_chain": item["event_chain"]} for item in event_records])

    report = validate_module.validate_dataset(events, evidence, gold, chains, raw_posts_path=raw, silver_tuples_path=silver)
    raw_text = raw.read_text(encoding="utf-8")

    assert "contact@example.com" not in raw_text
    assert "555-123-4567" not in raw_text
    assert report["errors"] == []
    assert report["num_raw_posts"] == 2
    assert report["num_silver_tuples"] == 2


def test_validate_dataset_rejects_silver_in_gold(tmp_path: Path) -> None:
    module = load_script("scripts/validate_dataset.py", "validate_silver_in_gold")
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "gold_tuples.jsonl"
    chains = tmp_path / "gold_event_chains.jsonl"

    write_jsonl(events, [{"event_id": "evt-1", "target_event": "Urban renewal", "event_chain": ["a"]}])
    write_jsonl(evidence, [{"evidence_id": "ev-1", "event_id": "evt-1", "url": "https://news.test/a", "text": "text"}])
    write_jsonl(
        tuples,
        [
            {
                "event_id": "evt-1",
                "stakeholder": "residents",
                "opinion": "opinion",
                "sentiment": "negative",
                "rationale": "rationale",
                "event_chain": ["a"],
                "evidence_ids": ["ev-1"],
                "support_score": 0.9,
                "support_label": "supported",
                "verified": True,
                "label_source": "llm_silver",
            }
        ],
    )
    write_jsonl(chains, [{"event_id": "evt-1", "event_chain": ["a"]}])

    report = module.validate_dataset(events, evidence, tuples, chains)

    assert any("llm_silver" in error for error in report["errors"])


def test_check_paper_readiness_blocks_empty_formal_dataset(tmp_path: Path, monkeypatch) -> None:
    module = load_script("scripts/check_paper_readiness.py", "check_paper_readiness")
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "gold_tuples.jsonl"
    chains = tmp_path / "gold_event_chains.jsonl"
    for path in (events, evidence, tuples, chains):
        path.write_text("", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = module.build_readiness_report(
        events_path=events,
        evidence_path=evidence,
        gold_tuples_path=tuples,
        gold_event_chains_path=chains,
        annotation_sheet_path=tmp_path / "annotation_sheet_formal.csv",
        filled_annotation_sheet_path=tmp_path / "annotation_sheet_formal_filled.csv",
        results_dir=tmp_path / "results",
    )

    assert report["status"] == "blocked"
    assert report["dataset"]["is_formal_dataset"] is False
    assert report["real_experiments_can_run"] is False
    assert any("events.jsonl" in item for item in report["missing_items"])
    assert any("OPENAI_API_KEY" in item for item in report["missing_items"])


def test_validate_dataset_rejects_gold_chain_unknown_event(tmp_path: Path) -> None:
    module = load_script("scripts/validate_dataset.py", "validate_gold_chain_event")
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "gold_tuples.jsonl"
    chains = tmp_path / "gold_event_chains.jsonl"

    write_jsonl(events, [{"event_id": "evt-1", "target_event": "Formal event", "event_chain": ["a"]}])
    write_jsonl(evidence, [{"evidence_id": "ev-1", "event_id": "evt-1", "url": "https://news.test/a", "text": "text"}])
    write_jsonl(
        tuples,
        [
            {
                "event_id": "evt-1",
                "stakeholder": "residents",
                "opinion": "opinion",
                "sentiment": "negative",
                "rationale": "rationale",
                "event_chain": ["a"],
                "evidence_ids": ["ev-1"],
                "support_score": 0.9,
                "support_label": "supported",
                "verified": True,
            }
        ],
    )
    write_jsonl(chains, [{"event_id": "evt-missing", "event_chain": ["a"], "evidence_ids": ["ev-missing"]}])

    report = module.validate_dataset(events, evidence, tuples, chains)

    assert any("gold_event_chains:1 references unknown event_id" in error for error in report["errors"])
    assert any("gold_event_chains:1 references unknown evidence_id" in error for error in report["errors"])
