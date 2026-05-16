import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_human_gold_audit_marks_ready_only_when_no_issues(tmp_path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "human_gold_tuples_v1.jsonl"
    chains = tmp_path / "human_gold_event_chains_v1.jsonl"
    manifest = tmp_path / "human_gold_manifest_v1.json"
    write_jsonl(events, [{"event_id": "E1"}])
    write_jsonl(evidence, [{"event_id": "E1", "evidence_id": "ev1", "text": "support"}])
    write_jsonl(tuples, [{
        "tuple_id": "T1",
        "event_id": "E1",
        "stakeholder": "stakeholder",
        "opinion": "opinion",
        "sentiment": "neutral",
        "rationale": "rationale",
        "evidence_ids": ["ev1"],
    }])
    write_jsonl(chains, [{
        "chain_id": "C1",
        "event_id": "E1",
        "event_chain": ["start", "end"],
        "evidence_ids": ["ev1"],
    }])
    manifest.write_text(json.dumps({"dataset_level": "human_gold", "ready_for_main_experiment": False}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_human_gold.py"),
            "--tuples",
            str(tuples),
            "--chains",
            str(chains),
            "--events",
            str(events),
            "--evidence",
            str(evidence),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads((tmp_path / "human_gold_audit.json").read_text(encoding="utf-8"))
    updated_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["total_issues"] == 0
    assert report["ready_for_main_experiment"] is True
    assert updated_manifest["ready_for_main_experiment"] is True
    assert "total_issues" in result.stdout


def test_human_gold_audit_reports_invalid_reference(tmp_path):
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "human_gold_tuples_v1.jsonl"
    chains = tmp_path / "human_gold_event_chains_v1.jsonl"
    manifest = tmp_path / "human_gold_manifest_v1.json"
    write_jsonl(events, [{"event_id": "E1"}])
    write_jsonl(evidence, [{"event_id": "E1", "evidence_id": "ev1", "text": "support"}])
    write_jsonl(tuples, [{
        "tuple_id": "T1",
        "event_id": "E1",
        "stakeholder": "stakeholder",
        "opinion": "opinion",
        "sentiment": "neutral",
        "rationale": "rationale",
        "evidence_ids": ["missing"],
    }])
    write_jsonl(chains, [{
        "chain_id": "C1",
        "event_id": "E1",
        "event_chain": ["start"],
        "evidence_ids": ["ev1"],
    }])
    manifest.write_text(json.dumps({"dataset_level": "human_gold", "ready_for_main_experiment": True}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_human_gold.py"),
            "--tuples",
            str(tuples),
            "--chains",
            str(chains),
            "--events",
            str(events),
            "--evidence",
            str(evidence),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads((tmp_path / "human_gold_audit.json").read_text(encoding="utf-8"))
    updated_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["total_issues"] > 0
    assert updated_manifest["ready_for_main_experiment"] is False
