from argparse import Namespace
import csv
import json
from pathlib import Path
import importlib.util


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "make_annotation_sheet.py"
SPEC = importlib.util.spec_from_file_location("make_annotation_sheet_script", SCRIPT_PATH)
sheet_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sheet_script)


def test_make_annotation_sheet_from_filtered_evidence(tmp_path):
    evidence = tmp_path / "evidence_filtered.jsonl"
    sheet = tmp_path / "annotation_sheet.csv"
    guideline = tmp_path / "annotation_guideline.md"
    summary = tmp_path / "annotation_summary.json"
    gold = tmp_path / "gold_tuples.jsonl"
    evidence.write_text(
        json.dumps(
            {
                "event_id": "E1",
                "evidence_id": "ev1",
                "source": "official",
                "platform": "gov.cn",
                "domain": "city.gov.cn",
                "url": "https://city.gov.cn/a",
                "publish_time": "2025-01-01",
                "quality_score": 0.9,
                "text": "居民投诉旧改补偿争议，业主不满安置方案。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    code = sheet_script.make_annotation_sheet(
        Namespace(
            input=str(evidence),
            output=str(sheet),
            guideline_output=str(guideline),
            summary_output=str(summary),
        )
    )

    with sheet.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    data = json.loads(summary.read_text(encoding="utf-8"))

    assert code == 0
    assert rows[0]["candidate_stakeholder"] == "居民/公众"
    assert rows[0]["candidate_sentiment"] == "negative"
    assert rows[0]["annotated_opinion"] == ""
    assert rows[0]["support_label"] == ""
    assert data["total_rows"] == 1
    assert "supported" in guideline.read_text(encoding="utf-8")
    assert not gold.exists()
