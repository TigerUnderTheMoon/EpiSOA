import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TUPLE_FIELDS = [
    "event_id",
    "tuple_id",
    "stakeholder",
    "opinion",
    "sentiment",
    "rationale",
    "event_chain",
    "evidence_ids",
    "evidence_texts",
    "evidence_source_types",
    "review_decision",
    "revised_stakeholder",
    "revised_opinion",
    "revised_sentiment",
    "revised_rationale",
    "revised_evidence_ids",
    "reviewer_note",
    "reviewer_id",
    "adjudication_status",
]

CHAIN_FIELDS = [
    "event_id",
    "chain_id",
    "event_chain",
    "evidence_ids",
    "evidence_texts",
    "evidence_source_types",
    "review_decision",
    "revised_event_chain",
    "revised_evidence_ids",
    "reviewer_note",
    "reviewer_id",
    "adjudication_status",
]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_files(tmp_path: Path) -> tuple[Path, Path]:
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    write_jsonl(events, [{"event_id": "E1"}])
    write_jsonl(evidence, [{"event_id": "E1", "evidence_id": "ev1", "text": "support"}])
    return events, evidence


def tuple_row(**overrides) -> dict:
    row = {
        "event_id": "E1",
        "tuple_id": "T1",
        "stakeholder": "stakeholder",
        "opinion": "opinion",
        "sentiment": "neutral",
        "rationale": "rationale",
        "event_chain": "start -> end",
        "evidence_ids": "ev1",
        "evidence_texts": "support text",
        "evidence_source_types": "news",
        "review_decision": "uncertain",
        "revised_stakeholder": "",
        "revised_opinion": "",
        "revised_sentiment": "",
        "revised_rationale": "",
        "revised_evidence_ids": "",
        "reviewer_note": "",
        "reviewer_id": "",
        "adjudication_status": "",
    }
    row.update(overrides)
    return row


def chain_row(**overrides) -> dict:
    row = {
        "event_id": "E1",
        "chain_id": "C1",
        "event_chain": "start -> end",
        "evidence_ids": "ev1",
        "evidence_texts": "support text",
        "evidence_source_types": "news",
        "review_decision": "uncertain",
        "revised_event_chain": "",
        "revised_evidence_ids": "",
        "reviewer_note": "",
        "reviewer_id": "",
        "adjudication_status": "",
    }
    row.update(overrides)
    return row


def run_audit(
    tmp_path: Path,
    *,
    tuple_rows: list[dict],
    chain_rows: list[dict],
    tuple_fields: list[str] = TUPLE_FIELDS,
    chain_fields: list[str] = CHAIN_FIELDS,
    check: bool = True,
):
    events, evidence = base_files(tmp_path)
    tuple_sheet = tmp_path / "tuple_sheet.csv"
    chain_sheet = tmp_path / "chain_sheet.csv"
    write_csv(tuple_sheet, tuple_fields, tuple_rows)
    write_csv(chain_sheet, chain_fields, chain_rows)
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_adjudication_sheet_before_review.py"),
            "--tuple-sheet",
            str(tuple_sheet),
            "--chain-sheet",
            str(chain_sheet),
            "--events",
            str(events),
            "--evidence",
            str(evidence),
            "--output-dir",
            str(tmp_path / "audit"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def read_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "audit" / "adjudication_sheet_pre_review_audit.json").read_text(encoding="utf-8"))


def test_pre_review_audit_accepts_complete_uncertain_sheets_and_does_not_modify_inputs(tmp_path):
    events, evidence = base_files(tmp_path)
    tuple_sheet = tmp_path / "tuple_sheet.csv"
    chain_sheet = tmp_path / "chain_sheet.csv"
    write_csv(tuple_sheet, TUPLE_FIELDS, [tuple_row()])
    write_csv(chain_sheet, CHAIN_FIELDS, [chain_row()])
    before = {path: digest(path) for path in (events, evidence, tuple_sheet, chain_sheet)}

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_adjudication_sheet_before_review.py"),
            "--tuple-sheet",
            str(tuple_sheet),
            "--chain-sheet",
            str(chain_sheet),
            "--events",
            str(events),
            "--evidence",
            str(evidence),
            "--output-dir",
            str(tmp_path / "audit"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = read_report(tmp_path)
    assert report["ready_for_human_review"] is True
    assert report["total_errors"] == 0
    assert before == {path: digest(path) for path in before}


def test_pre_review_audit_reports_missing_required_field(tmp_path):
    fields = [field for field in TUPLE_FIELDS if field != "evidence_texts"]
    result = run_audit(tmp_path, tuple_rows=[tuple_row()], chain_rows=[chain_row()], tuple_fields=fields, check=False)

    assert result.returncode == 1
    report = read_report(tmp_path)
    assert report["error_counts"]["tuple_required_field_present"] == 1


def test_pre_review_audit_reports_empty_evidence_texts(tmp_path):
    result = run_audit(tmp_path, tuple_rows=[tuple_row(evidence_texts="")], chain_rows=[chain_row()], check=False)

    assert result.returncode == 1
    report = read_report(tmp_path)
    assert report["error_counts"]["tuple_evidence_texts_nonempty"] == 1


def test_pre_review_audit_reports_invalid_evidence_id(tmp_path):
    result = run_audit(tmp_path, tuple_rows=[tuple_row(evidence_ids="missing")], chain_rows=[chain_row()], check=False)

    assert result.returncode == 1
    report = read_report(tmp_path)
    assert report["error_counts"]["tuple_evidence_id_exists"] == 1


def test_pre_review_audit_requires_default_uncertain(tmp_path):
    result = run_audit(tmp_path, tuple_rows=[tuple_row(review_decision="accept")], chain_rows=[chain_row()], check=False)

    assert result.returncode == 1
    report = read_report(tmp_path)
    assert report["error_counts"]["tuple_review_decision_default_uncertain"] == 1
