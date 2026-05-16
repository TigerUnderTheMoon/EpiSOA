import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_export_silver_does_not_modify_original_files(tmp_path):
    src = tmp_path / "annotation"
    tuples = src / "llm_gold_tuples.jsonl"
    chains = src / "llm_gold_event_chains.jsonl"
    write_jsonl(tuples, [{"event_id": "E1", "candidate_id": "T1", "source_type": "llm_preannotation"}])
    write_jsonl(chains, [{"event_id": "E1", "candidate_chain_id": "C1", "source_type": "llm_preannotation"}])
    before = {tuples: digest(tuples), chains: digest(chains)}

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "export_silver_benchmark.py"),
            "--tuples",
            str(tuples),
            "--chains",
            str(chains),
            "--output-dir",
            str(tmp_path / "silver"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert before == {tuples: digest(tuples), chains: digest(chains)}
    manifest = json.loads((tmp_path / "silver" / "silver_manifest_v1.json").read_text(encoding="utf-8"))
    assert manifest["dataset_level"] == "silver"
    assert manifest["source"] == "llm_preannotation"
    assert manifest["human_verified"] is False
    assert manifest["auto_reviewer_accept_all"] is True
    assert manifest["original_files_modified"] is False
    assert "silver_tuples_v1.jsonl" in result.stdout
