import json
from pathlib import Path

from scripts.audit_cross_source_support import audit_cross_source_support


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_cross_source_audit_routes_single_source_to_human_review(tmp_path):
    evidence = tmp_path / "evidence.jsonl"
    tuples = tmp_path / "tuples.jsonl"
    chains = tmp_path / "chains.jsonl"
    write_jsonl(evidence, [
        {"event_id": "E1", "evidence_id": "ev1", "url": "https://a.example/news", "text": "a"},
        {"event_id": "E1", "evidence_id": "ev2", "url": "https://b.example/news", "text": "b"},
    ])
    write_jsonl(tuples, [
        {"event_id": "E1", "candidate_id": "T1", "evidence_ids": ["ev1"]},
        {"event_id": "E1", "candidate_id": "T2", "evidence_ids": ["ev1", "ev2"]},
    ])
    write_jsonl(chains, [])

    report = audit_cross_source_support(
        tuples_path=tuples,
        chains_path=chains,
        evidence_path=evidence,
        output_dir=tmp_path / "audit",
    )

    assert report["low_confidence_total"] == 1
    audit = json.loads((tmp_path / "audit" / "cross_source_support_audit.json").read_text(encoding="utf-8"))
    assert audit["counts"]["low_confidence"] == 1
    assert audit["counts"]["silver_candidate"] == 1
