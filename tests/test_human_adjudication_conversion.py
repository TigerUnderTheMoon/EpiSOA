import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def base_files(tmp_path: Path) -> tuple[Path, Path]:
    events = tmp_path / "events.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    write_jsonl(events, [{"event_id": "E1", "domain": "education"}])
    write_jsonl(evidence, [{"event_id": "E1", "evidence_id": "ev1", "text": "support"}])
    return events, evidence


def run_convert(tmp_path: Path, tuple_rows: list[dict], chain_rows: list[dict], check: bool = True):
    events, evidence = base_files(tmp_path)
    tuple_sheet = tmp_path / "tuple.csv"
    chain_sheet = tmp_path / "chain.csv"
    write_csv(tuple_sheet, tuple_rows)
    write_csv(chain_sheet, chain_rows)
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "convert_adjudication_to_human_gold.py"),
            "--tuple-sheet",
            str(tuple_sheet),
            "--chain-sheet",
            str(chain_sheet),
            "--events",
            str(events),
            "--evidence",
            str(evidence),
            "--output-dir",
            str(tmp_path / "human_gold"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def test_convert_handles_accept_revise_drop_add_missing_and_uncertain(tmp_path):
    tuple_rows = [
        row("T_accept", "accept", stakeholder="old", opinion="keep", sentiment="neutral", evidence_ids="ev1"),
        row("T_revise", "revise", revised_stakeholder="new", revised_opinion="changed", revised_sentiment="positive", revised_rationale="new rationale", revised_evidence_ids="ev1"),
        row("T_drop", "drop", stakeholder="drop", opinion="drop", sentiment="negative", evidence_ids="ev1"),
        row("T_uncertain", "uncertain", stakeholder="uncertain", opinion="uncertain", sentiment="neutral", evidence_ids="ev1"),
        row("", "add_missing", revised_stakeholder="added", revised_opinion="missing tuple", revised_sentiment="mixed", revised_rationale="added rationale", revised_evidence_ids="ev1"),
    ]
    chain_rows = [
        {"event_id": "E1", "chain_id": "C1", "event_chain": "start -> end", "evidence_ids": "ev1", "review_decision": "accept"}
    ]

    run_convert(tmp_path, tuple_rows, chain_rows)

    tuples = read_jsonl(tmp_path / "human_gold" / "human_gold_tuples_v1.jsonl")
    assert [item["review_decision"] for item in tuples] == ["accept", "revise", "add_missing"]
    assert tuples[1]["stakeholder"] == "new"
    assert tuples[1]["opinion"] == "changed"
    assert tuples[2]["tuple_id"].startswith("HG_E1_")
    log_text = (tmp_path / "human_gold" / "rejected_or_uncertain_log.csv").read_text(encoding="utf-8-sig")
    assert "T_drop" in log_text
    assert "T_uncertain" in log_text
    manifest = json.loads((tmp_path / "human_gold" / "human_gold_manifest_v1.json").read_text(encoding="utf-8"))
    assert manifest["dataset_level"] == "human_gold"
    assert manifest["human_verified"] is True
    assert manifest["ready_for_main_experiment"] is False


def test_invalid_evidence_id_fails_conversion(tmp_path):
    tuple_rows = [row("T_bad", "accept", stakeholder="x", opinion="y", sentiment="neutral", evidence_ids="missing")]
    chain_rows = [{"event_id": "E1", "chain_id": "C1", "event_chain": "start", "evidence_ids": "ev1", "review_decision": "accept"}]

    result = run_convert(tmp_path, tuple_rows, chain_rows, check=False)

    assert result.returncode != 0
    assert "unknown evidence_id missing" in (result.stderr + result.stdout)


def row(tuple_id: str, decision: str, **kwargs) -> dict:
    base = {
        "event_id": "E1",
        "tuple_id": tuple_id,
        "stakeholder": kwargs.pop("stakeholder", ""),
        "opinion": kwargs.pop("opinion", ""),
        "sentiment": kwargs.pop("sentiment", ""),
        "rationale": kwargs.pop("rationale", "rationale"),
        "evidence_ids": kwargs.pop("evidence_ids", ""),
        "review_decision": decision,
        "revised_stakeholder": "",
        "revised_opinion": "",
        "revised_sentiment": "",
        "revised_rationale": "",
        "revised_evidence_ids": "",
    }
    base.update(kwargs)
    return base
