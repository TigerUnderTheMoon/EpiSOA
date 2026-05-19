import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_select_pilot_review_events_outputs_five_unique_events(tmp_path):
    coverage = tmp_path / "evidence_coverage_by_event.csv"
    gold_quality = tmp_path / "gold_quality_by_event.csv"
    probe = tmp_path / "model_capability_probe_results.csv"
    chain_sheet = tmp_path / "human_chain_adjudication_sheet.csv"
    output_dir = tmp_path / "human_gold_v1"
    write_csv(coverage, [
        {"event_id": "E1", "gold_evidence_in_prompt_ratio": "1.0", "gold_evidence_in_chain_ratio": "0.5", "gold_evidence_id_count": "3"},
        {"event_id": "E2", "gold_evidence_in_prompt_ratio": "0.0", "gold_evidence_in_chain_ratio": "0.0", "gold_evidence_id_count": "4"},
        {"event_id": "E3", "gold_evidence_in_prompt_ratio": "0.6", "gold_evidence_in_chain_ratio": "0.3", "gold_evidence_id_count": "2"},
        {"event_id": "E4", "gold_evidence_in_prompt_ratio": "0.5", "gold_evidence_in_chain_ratio": "0.2", "gold_evidence_id_count": "2"},
        {"event_id": "E5", "gold_evidence_in_prompt_ratio": "0.4", "gold_evidence_in_chain_ratio": "0.1", "gold_evidence_id_count": "2"},
    ])
    write_csv(gold_quality, [
        {"event_id": "E1", "gold_tuple_count": "1", "unique_gold_evidence_count": "3"},
        {"event_id": "E2", "gold_tuple_count": "2", "unique_gold_evidence_count": "4"},
        {"event_id": "E3", "gold_tuple_count": "9", "unique_gold_evidence_count": "5"},
        {"event_id": "E4", "gold_tuple_count": "3", "unique_gold_evidence_count": "2"},
        {"event_id": "E5", "gold_tuple_count": "4", "unique_gold_evidence_count": "2"},
    ])
    write_csv(probe, [
        {"scope": "event", "event_id": "E1", "Tuple-F1-soft": "0.8", "zero_pred_count": "0", "error_category": "ok"},
        {"scope": "event", "event_id": "E2", "Tuple-F1-soft": "0.7", "zero_pred_count": "0", "error_category": "ok"},
        {"scope": "event", "event_id": "E3", "Tuple-F1-soft": "0.6", "zero_pred_count": "0", "error_category": "ok"},
        {"scope": "event", "event_id": "E4", "Tuple-F1-soft": "0.5", "zero_pred_count": "0", "error_category": "ok"},
        {"scope": "event", "event_id": "E5", "Tuple-F1-soft": "0.0", "zero_pred_count": "1", "error_category": "zero_prediction"},
    ])
    write_csv(chain_sheet, [
        {"event_id": "E1", "chain_id": "C1"},
        {"event_id": "E2", "chain_id": "C2"},
        {"event_id": "E3", "chain_id": "C3"},
        {"event_id": "E4", "chain_id": "C4a"},
        {"event_id": "E4", "chain_id": "C4b"},
        {"event_id": "E4", "chain_id": "C4c"},
        {"event_id": "E5", "chain_id": "C5"},
    ])

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "select_pilot_review_events.py"),
            "--coverage",
            str(coverage),
            "--gold-quality",
            str(gold_quality),
            "--model-probe",
            str(probe),
            "--chain-sheet",
            str(chain_sheet),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads((output_dir / "pilot_events_v1.json").read_text(encoding="utf-8"))
    assert [row["event_id"] for row in payload["events"]] == ["E1", "E2", "E3", "E4", "E5"]
    assert (output_dir / "pilot_event_selection_report.md").exists()


def test_build_pilot_sheets_filters_without_modifying_full_sheets(tmp_path):
    output_dir = tmp_path / "human_gold_v1"
    pilot_events = output_dir / "pilot_events_v1.json"
    pilot_events.parent.mkdir(parents=True, exist_ok=True)
    pilot_events.write_text(json.dumps({"events": [{"event_id": f"E{i}"} for i in range(1, 6)]}), encoding="utf-8")
    tuple_sheet = output_dir / "human_tuple_adjudication_sheet.csv"
    chain_sheet = output_dir / "human_chain_adjudication_sheet.csv"
    write_csv(tuple_sheet, [{"event_id": "E1", "tuple_id": "T1"}, {"event_id": "E6", "tuple_id": "T6"}])
    write_csv(chain_sheet, [{"event_id": "E1", "chain_id": "C1"}, {"event_id": "E6", "chain_id": "C6"}])
    before = {tuple_sheet: digest(tuple_sheet), chain_sheet: digest(chain_sheet)}

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_pilot_adjudication_sheet.py"),
            "--pilot-events",
            str(pilot_events),
            "--tuple-sheet",
            str(tuple_sheet),
            "--chain-sheet",
            str(chain_sheet),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert before == {path: digest(path) for path in before}
    assert "T1" in (output_dir / "human_tuple_adjudication_sheet_pilot5.csv").read_text(encoding="utf-8-sig")
    assert "T6" not in (output_dir / "human_tuple_adjudication_sheet_pilot5.csv").read_text(encoding="utf-8-sig")


def test_convert_and_audit_pilot_mode_use_only_pilot_outputs(tmp_path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    output_dir = tmp_path / "human_gold_v1"
    tuple_sheet = output_dir / "human_tuple_adjudication_sheet_pilot5.csv"
    chain_sheet = output_dir / "human_chain_adjudication_sheet_pilot5.csv"
    write_jsonl(events, [{"event_id": "E1"}])
    write_jsonl(evidence, [{"event_id": "E1", "evidence_id": "ev1", "text": "support"}])
    write_csv(tuple_sheet, [{
        "event_id": "E1",
        "tuple_id": "T1",
        "stakeholder": "stakeholder",
        "opinion": "opinion",
        "sentiment": "neutral",
        "rationale": "rationale",
        "evidence_ids": "ev1",
        "review_decision": "accept",
        "reviewer_id": "R1",
        "reviewer_note": "",
        "adjudication_status": "pilot_done",
    }])
    write_csv(chain_sheet, [{
        "event_id": "E1",
        "chain_id": "C1",
        "event_chain": "start -> end",
        "evidence_ids": "ev1",
        "review_decision": "accept",
        "reviewer_id": "R1",
        "reviewer_note": "",
        "adjudication_status": "pilot_done",
    }])

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "convert_adjudication_to_human_gold.py"),
            "--pilot",
            "--evidence",
            str(evidence),
            "--events",
            str(events),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert (output_dir / "pilot_human_gold_tuples_v1.jsonl").exists()
    assert (output_dir / "pilot_human_gold_event_chains_v1.jsonl").exists()
    assert (output_dir / "pilot_human_gold_manifest_v1.json").exists()
    assert not (output_dir / "human_gold_tuples_v1.jsonl").exists()
    assert not (output_dir / "human_gold_event_chains_v1.jsonl").exists()

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_human_gold.py"),
            "--pilot",
            "--evidence",
            str(evidence),
            "--events",
            str(events),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert (output_dir / "pilot_human_gold_audit.json").exists()
    assert not (output_dir / "human_gold_audit.json").exists()
    manifest = json.loads((output_dir / "pilot_human_gold_manifest_v1.json").read_text(encoding="utf-8"))
    assert manifest["dataset_level"] == "pilot_human_gold"
    assert manifest["ready_for_main_experiment"] is True
