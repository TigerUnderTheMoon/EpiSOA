import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def test_build_human_adjudication_sheet_scores_and_sorts_priority(tmp_path):
    silver_dir = tmp_path / "silver_v1"
    evidence_path = tmp_path / "evidence.jsonl"
    output_dir = tmp_path / "human_gold_v1"
    write_jsonl(
        evidence_path,
        [
            {"event_id": "E1", "evidence_id": "ev1", "source_type": "news", "source": "news", "text": "thin"},
            {
                "event_id": "E1",
                "evidence_id": "ev2",
                "source_type": "news",
                "source": "news",
                "text": "residents describe the problem and local officials response with detailed handling " * 20,
                "full_text": "full article residents describe the problem and local officials response with detailed handling " * 30,
            },
            {
                "event_id": "E1",
                "evidence_id": "ev3",
                "source_type": "official",
                "source": "official",
                "text": "official resolution notice explains coordination and resolved actions in detail " * 2,
            },
        ],
    )
    write_jsonl(
        silver_dir / "silver_tuples_v1.jsonl",
        [
            {
                "event_id": "E1",
                "candidate_id": "T_low",
                "stakeholder": "residents",
                "opinion": "request clearer handling plan",
                "sentiment": "negative",
                "rationale": "two evidence records support the stakeholder concern",
                "evidence_ids": ["ev2", "ev3"],
                "support_label": "supported",
            },
            {
                "event_id": "E1",
                "candidate_id": "T_high",
                "stakeholder": "x",
                "opinion": "bad",
                "sentiment": "negative",
                "rationale": "no",
                "evidence_ids": ["ev1"],
                "support_label": "partially_supported",
                "independent_source_count": 1,
                "confidence_route": "low_confidence",
                "required_action": "human_review_required",
            },
        ],
    )
    write_jsonl(
        silver_dir / "silver_event_chains_v1.jsonl",
        [
            {
                "event_id": "E1",
                "chain_id": "C_low",
                "event_chain": ["trigger", "response", "resolution"],
                "evidence_ids": ["ev2", "ev3"],
            },
            {
                "event_id": "E1",
                "chain_id": "C_high",
                "event_chain": ["start"],
                "evidence_ids": ["ev1"],
            },
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_human_adjudication_sheet.py"),
            "--silver-tuples",
            str(silver_dir / "silver_tuples_v1.jsonl"),
            "--silver-chains",
            str(silver_dir / "silver_event_chains_v1.jsonl"),
            "--evidence",
            str(evidence_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    summary = json.loads(result.stdout)
    tuple_fields, tuple_rows = read_csv(output_dir / "human_tuple_adjudication_sheet.csv")
    chain_fields, chain_rows = read_csv(output_dir / "human_chain_adjudication_sheet.csv")
    assert tuple_fields.index("adjudication_priority_score") < tuple_fields.index("review_decision")
    assert "evidence_texts" in tuple_fields
    assert "evidence_urls" in tuple_fields
    assert "event_chain" not in tuple_fields
    assert "evidence_texts_preview" not in tuple_fields
    assert "evidence_texts_full" not in tuple_fields
    assert "evidence_texts_full_status" not in tuple_fields
    assert "evidence_titles" not in tuple_fields
    assert "evidence_dates" not in tuple_fields
    assert chain_fields.index("priority_reason") < chain_fields.index("review_decision")
    assert [row["tuple_id"] for row in tuple_rows] == ["T_high", "T_low"]
    assert [row["chain_id"] for row in chain_rows] == ["C_high", "C_low"]
    assert float(tuple_rows[0]["adjudication_priority_score"]) > float(tuple_rows[1]["adjudication_priority_score"])
    assert float(chain_rows[0]["adjudication_priority_score"]) > float(chain_rows[1]["adjudication_priority_score"])
    assert "weak_support_label" in tuple_rows[0]["priority_reason"]
    assert tuple_rows[0]["confidence_route"] == "low_confidence"
    assert tuple_rows[0]["required_action"] == "human_review_required"
    assert "low_confidence_cross_source" in tuple_rows[0]["priority_reason"]
    assert "short_chain" in chain_rows[0]["priority_reason"]
    assert summary["priority_bucket_distribution"]["tuples"]["high"] == 1
