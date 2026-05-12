import csv
import importlib.util
from pathlib import Path

from episoa.data.loader import write_jsonl


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_gold_pilot_audit_sheet.py"
SPEC = importlib.util.spec_from_file_location("build_gold_pilot_audit_sheet_script", SCRIPT_PATH)
script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(script)


def test_normal_tuple_written_to_audit_sheet(tmp_path):
    paths = write_inputs(tmp_path)

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
    )

    assert rows[0]["event_id"] == "E001"
    assert rows[0]["tuple_id"] == "LLM_E001_001"
    assert rows[0]["stakeholder"] == "residents"
    assert rows[0]["human_judgment"] == ""


def test_event_without_tuple_keeps_blank_audit_row(tmp_path):
    paths = write_inputs(tmp_path)

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
    )

    blank = next(row for row in rows if row["event_id"] == "E002")
    assert blank["tuple_id"] == ""
    assert blank["tuple_generation_status"] == "not_run"
    assert blank["human_judgment"] == ""
    assert blank["error_type"] == ""


def test_evidence_ids_expand_supporting_text(tmp_path):
    paths = write_inputs(tmp_path)

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
    )

    assert "ev-1: Residents object to compensation." in rows[0]["supporting_evidence_text"]


def test_event_ids_and_max_events_filtering(tmp_path):
    paths = write_inputs(tmp_path)

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
        event_ids=["E002", "E003"],
        max_events=1,
    )

    assert [row["event_id"] for row in rows] == ["E002"]


def test_write_csv_uses_expected_fields(tmp_path):
    output = tmp_path / "audit.csv"
    script.write_csv(output, [script.blank_row("E001")])

    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["event_id"] == "E001"
    assert "guideline_change_needed" in rows[0]


def test_api_failure_event_not_auto_marked_missing_tuple(tmp_path):
    paths = write_inputs(tmp_path)
    write_jsonl(
        paths["audit"],
        [{"event_id": "E002", "task_type": "tuple", "request_status": "failed", "parse_status": "not_run", "num_candidates": 0, "error_type": "api_timeout", "error_message": "timed out"}],
    )

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
    )
    row = next(item for item in rows if item["event_id"] == "E002")

    assert row["tuple_generation_status"] == "api_failure"
    assert row["human_judgment"] == ""
    assert row["error_type"] == ""
    assert "tuple_error=api_timeout" in row["preannotation_note"]


def test_success_zero_candidate_event_is_marked_missing_tuple(tmp_path):
    paths = write_inputs(tmp_path)
    write_jsonl(
        paths["audit"],
        [{"event_id": "E002", "task_type": "tuple", "request_status": "ok", "parse_status": "parsed", "num_candidates": 0, "error_type": "", "error_message": ""}],
    )

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
    )
    row = next(item for item in rows if item["event_id"] == "E002")

    assert row["tuple_generation_status"] == "no_candidate"
    assert row["human_judgment"] == "missing_gold_tuple"
    assert row["error_type"] == "missing_tuple"


def test_parse_failure_event_is_not_marked_missing_tuple(tmp_path):
    paths = write_inputs(tmp_path)
    write_jsonl(
        paths["audit"],
        [{"event_id": "E002", "task_type": "tuple", "request_status": "ok", "parse_status": "failed", "num_candidates": 0, "error_type": "invalid_json", "error_message": "bad json"}],
    )

    rows = script.build_audit_rows(
        tuples_path=paths["tuples"],
        chains_path=paths["chains"],
        audit_path=paths["audit"],
        evidence_path=paths["evidence"],
        events_path=paths["events"],
    )
    row = next(item for item in rows if item["event_id"] == "E002")

    assert row["tuple_generation_status"] == "parse_failure"
    assert row["human_judgment"] == ""
    assert row["error_type"] == "parse_failure"


def write_inputs(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "llm_gold_tuples.jsonl"
    chains = tmp_path / "llm_gold_event_chains.jsonl"
    audit = tmp_path / "llm_preannotation_audit.jsonl"
    write_jsonl(
        events,
        [
            {"event_id": "E001", "event_name": "event one"},
            {"event_id": "E002", "event_name": "event two"},
            {"event_id": "E003", "event_name": "event three"},
        ],
    )
    write_jsonl(
        evidence,
        [
            {"event_id": "E001", "evidence_id": "ev-1", "text": "Residents object to compensation."},
            {"event_id": "E002", "evidence_id": "ev-2", "text": "Official response."},
        ],
    )
    write_jsonl(
        tuples,
        [
            {
                "event_id": "E001",
                "candidate_id": "LLM_E001_001",
                "stakeholder": "residents",
                "opinion": "compensation is low",
                "sentiment": "negative",
                "rationale": "Residents objected.",
                "evidence_ids": ["ev-1"],
            }
        ],
    )
    write_jsonl(chains, [{"event_id": "E001", "event_chain": ["complaint"], "evidence_ids": ["ev-1"]}])
    write_jsonl(audit, [])
    return {"events": events, "evidence": evidence, "tuples": tuples, "chains": chains, "audit": audit}
