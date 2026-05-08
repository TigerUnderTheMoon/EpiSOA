import json
from pathlib import Path

from episoa.annotation.gold_annotation import (
    build_gold_review_outputs,
    build_gold_event_chains,
    build_review_rows,
    convert_review_sheets_to_gold,
    read_jsonl,
    validate_gold_dataset,
    write_csv_rows,
    write_jsonl,
    TUPLE_REVIEW_FIELDS,
    NEW_TUPLE_FIELDS,
)


def test_reads_verified_and_generates_review_rows():
    rows = build_review_rows([verified_row()], events(), evidence_rows(), chains())

    assert len(rows) == 1
    assert rows[0]["tuple_id"] == "E012_SOA_001"
    assert rows[0]["review_status"] == "unreviewed"


def test_supported_tuple_prefills_gold_fields():
    row = build_review_rows([verified_row(label="supported")], events(), evidence_rows(), chains())[0]

    assert row["gold_stakeholder"] == "学生"
    assert row["gold_opinion"] == "食堂食品安全存在问题"
    assert row["gold_support_label"] == "supported"
    assert row["human_decision"] == "need_review"


def test_partially_supported_keeps_issue_flags_and_rationale():
    row = build_review_rows(
        [verified_row(label="partially_supported", issue_flags=["stakeholder_not_supported"])],
        events(),
        evidence_rows(),
        chains(),
    )[0]

    assert row["gold_support_label"] == "partially_supported"
    assert "证据支持候选元组" in row["gold_notes"]
    assert "stakeholder_not_supported" in row["gold_notes"]


def test_unsupported_tuple_does_not_auto_enter_gold(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    row = reviewed_row(human_decision="need_review", review_status="unreviewed", support_label="unsupported")
    write_csv_rows(review_path, [row], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(review_path, new_path, evidence_path, events_path, output_dir)

    assert read_jsonl(output_dir / "gold_tuples.jsonl") == []


def test_unreviewed_row_does_not_enter_gold(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    write_csv_rows(review_path, [reviewed_row(review_status="unreviewed")], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(review_path, new_path, evidence_path, events_path, output_dir)

    assert read_jsonl(output_dir / "gold_tuples.jsonl") == []


def test_reject_row_does_not_enter_gold(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    write_csv_rows(review_path, [reviewed_row(human_decision="reject")], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(review_path, new_path, evidence_path, events_path, output_dir)

    assert read_jsonl(output_dir / "gold_tuples.jsonl") == []


def test_accept_reviewed_row_enters_gold(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    write_csv_rows(review_path, [reviewed_row()], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(review_path, new_path, evidence_path, events_path, output_dir)
    gold = read_jsonl(output_dir / "gold_tuples.jsonl")

    assert len(gold) == 1
    assert gold[0]["annotation_provenance"]["source"] == "human_reviewed_llm_assisted"


def test_revise_uses_gold_fields_not_candidate_fields(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    row = reviewed_row(human_decision="revise")
    row["candidate_opinion"] = "候选观点"
    row["gold_opinion"] = "人工修正观点"
    write_csv_rows(review_path, [row], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(review_path, new_path, evidence_path, events_path, output_dir)

    assert read_jsonl(output_dir / "gold_tuples.jsonl")[0]["opinion"] == "人工修正观点"


def test_missing_evidence_id_validation_is_hard_error(tmp_path):
    paths = write_gold_validation_inputs(tmp_path, evidence_ids=["missing"])

    report = validate_gold_dataset(*paths)

    assert any(err["check"] == "evidence_id_exists" for err in report["hard_errors"])


def test_invalid_sentiment_validation_is_hard_error(tmp_path):
    paths = write_gold_validation_inputs(tmp_path, sentiment="angry")

    report = validate_gold_dataset(*paths)

    assert any(err["check"] == "sentiment_valid" for err in report["hard_errors"])


def test_invalid_support_label_validation_is_hard_error(tmp_path):
    paths = write_gold_validation_inputs(tmp_path, support_label="sure")

    report = validate_gold_dataset(*paths)

    assert any(err["check"] == "support_label_valid" for err in report["hard_errors"])


def test_gold_event_chains_group_by_event_and_stage():
    rows = [
        gold_tuple("G_E012_001", stage="conflict", evidence_ids=["ev-1"]),
        gold_tuple("G_E012_002", stage="conflict", evidence_ids=["ev-2"]),
        gold_tuple("G_E012_003", stage="response", evidence_ids=["ev-1"]),
    ]

    chains_out = build_gold_event_chains(rows)

    assert len(chains_out) == 2
    conflict = next(row for row in chains_out if row["stage"] == "conflict")
    assert conflict["evidence_ids"] == ["ev-1", "ev-2"]
    assert conflict["source_gold_tuple_ids"] == ["G_E012_001", "G_E012_002"]


def test_default_does_not_overwrite_dataset_gold(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    existing = dataset_dir / "gold_tuples.jsonl"
    existing.write_text("KEEP\n", encoding="utf-8")
    write_csv_rows(review_path, [reviewed_row()], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(review_path, new_path, evidence_path, events_path, output_dir, dataset_dir=dataset_dir)

    assert existing.read_text(encoding="utf-8") == "KEEP\n"


def test_write_to_dataset_gold_copies_only_when_flagged(tmp_path):
    review_path, new_path, evidence_path, events_path, output_dir = write_conversion_inputs(tmp_path)
    dataset_dir = tmp_path / "dataset"
    write_csv_rows(review_path, [reviewed_row()], TUPLE_REVIEW_FIELDS)
    write_csv_rows(new_path, [], NEW_TUPLE_FIELDS)

    convert_review_sheets_to_gold(
        review_path,
        new_path,
        evidence_path,
        events_path,
        output_dir,
        write_to_dataset_gold=True,
        dataset_dir=dataset_dir,
    )

    assert (dataset_dir / "gold_tuples.jsonl").exists()
    assert (dataset_dir / "gold_event_chains.jsonl").exists()


def test_dry_run_does_not_write_formal_outputs(tmp_path):
    summary = build_gold_review_outputs(
        events_path=write_jsonl_file(tmp_path / "events.jsonl", events()),
        evidence_path=write_jsonl_file(tmp_path / "evidence.jsonl", evidence_rows()),
        verified_path=write_jsonl_file(tmp_path / "verified.jsonl", [verified_row()]),
        chains_path=write_jsonl_file(tmp_path / "chains.jsonl", chains()),
        annotation_sheet_path=tmp_path / "annotation.csv",
        output_dir=tmp_path / "gold_annotation",
        dry_run=True,
    )

    assert summary["dry_run"] is True
    assert not (tmp_path / "gold_annotation" / "gold_tuple_review_sheet.csv").exists()


def test_use_llm_prelabel_not_passed_does_not_call_llm(tmp_path):
    calls = {"count": 0}

    def fake_prelabeler(_event, _evidence):
        calls["count"] += 1
        return []

    build_gold_review_outputs(
        events_path=write_jsonl_file(tmp_path / "events.jsonl", events()),
        evidence_path=write_jsonl_file(tmp_path / "evidence.jsonl", evidence_rows()),
        verified_path=write_jsonl_file(tmp_path / "verified.jsonl", [verified_row()]),
        chains_path=write_jsonl_file(tmp_path / "chains.jsonl", chains()),
        annotation_sheet_path=tmp_path / "annotation.csv",
        output_dir=tmp_path / "gold_annotation",
        use_llm_prelabel=False,
        llm_prelabeler=fake_prelabeler,
    )

    assert calls["count"] == 0


def write_conversion_inputs(tmp_path: Path):
    review_path = tmp_path / "review.csv"
    new_path = tmp_path / "new.csv"
    evidence_path = write_jsonl_file(tmp_path / "evidence.jsonl", evidence_rows())
    events_path = write_jsonl_file(tmp_path / "events.jsonl", events())
    output_dir = tmp_path / "gold_export"
    return review_path, new_path, evidence_path, events_path, output_dir


def write_gold_validation_inputs(tmp_path: Path, evidence_ids=None, sentiment="negative", support_label="supported"):
    evidence_path = write_jsonl_file(tmp_path / "evidence.jsonl", evidence_rows())
    events_path = write_jsonl_file(tmp_path / "events.jsonl", events())
    gold_tuples = tmp_path / "gold_tuples.jsonl"
    gold_chains = tmp_path / "gold_event_chains.jsonl"
    write_jsonl(gold_tuples, [gold_tuple("G_E012_001", evidence_ids=evidence_ids or ["ev-1"], sentiment=sentiment, support_label=support_label)])
    write_jsonl(gold_chains, [{"event_id": "E012", "gold_chain_id": "GC_E012_001", "stage": "conflict", "order": 3, "evidence_ids": ["ev-1"], "summary": "summary", "source_gold_tuple_ids": ["G_E012_001"], "annotation_provenance": {"source": "human_reviewed_llm_assisted"}}])
    return gold_tuples, gold_chains, evidence_path, events_path


def write_jsonl_file(path: Path, rows):
    write_jsonl(path, rows)
    return path


def events():
    return [{"event_id": "E012", "event_name": "校园食品安全事件", "event_description": "食堂异物争议"}]


def evidence_rows():
    return [{"event_id": "E012", "evidence_id": "ev-1", "source": "news", "domain": "example.test", "url": "https://example.test/1", "title": "食堂", "text": "学生反映食堂饭菜中出现异物。", "quality_score": 0.9}]


def chains():
    return [{"event_id": "E012", "chain_confidence": 0.8, "missing_stages": ["response"], "stages": [{"stage": "conflict", "evidence": [{"evidence_id": "ev-1"}]}]}]


def verified_row(label="supported", issue_flags=None):
    return {
        "event_id": "E012",
        "tuple_id": "E012_SOA_001",
        "stakeholder": "学生",
        "opinion": "食堂食品安全存在问题",
        "sentiment": "negative",
        "rationale": "学生反映食堂饭菜中出现异物。",
        "evidence_ids": ["ev-1"],
        "event_chain_stage": "conflict",
        "candidate_confidence": 0.9,
        "verification_label": label,
        "verification_score": 1.0,
        "verification_rationale": "证据支持候选元组。",
        "evidence_quotes": ["学生反映食堂饭菜中出现异物"],
        "issue_flags": issue_flags or ["no_issue"],
    }


def reviewed_row(human_decision="accept", review_status="reviewed", support_label="supported"):
    row = build_review_rows([verified_row(label=support_label)], events(), evidence_rows(), chains())[0]
    row["human_decision"] = human_decision
    row["review_status"] = review_status
    row["annotator_id"] = "A1"
    return row


def gold_tuple(tuple_id, stage="conflict", evidence_ids=None, sentiment="negative", support_label="supported"):
    return {
        "event_id": "E012",
        "gold_tuple_id": tuple_id,
        "stakeholder": "学生",
        "opinion": "食堂食品安全存在问题",
        "sentiment": sentiment,
        "rationale": "学生反映食堂饭菜中出现异物。",
        "evidence_ids": evidence_ids or ["ev-1"],
        "event_chain_stage": stage,
        "support_label": support_label,
        "source_candidate_tuple_id": "E012_SOA_001",
        "annotation_provenance": {
            "source": "human_reviewed_llm_assisted",
            "human_decision": "accept",
            "review_status": "reviewed",
            "annotator_id": "A1",
            "adjudication_status": "",
            "notes": "",
        },
    }

