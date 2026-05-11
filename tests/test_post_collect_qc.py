from argparse import Namespace
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "post_collect_qc.py"
SPEC = importlib.util.spec_from_file_location("post_collect_qc_script", SCRIPT_PATH)
post_collect_qc = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(post_collect_qc)


def test_post_collect_qc_passes_valid_collection(tmp_path):
    paths = write_collection(
        tmp_path,
        events=[event("E001"), event("E002")],
        raw_rows=[
            raw("r1", "E001", "official"),
            raw("r2", "E001", "public_social"),
            raw("r3", "E002", "official"),
            raw("r4", "E002", "forum"),
        ],
        plans=[plan("E001"), plan("E002")],
        coverage=coverage(["E001", "E002"]),
    )

    code = post_collect_qc.run_qc(args(paths, min_raw_per_event=2))

    report = read_report(paths)
    assert code == 0
    assert report["status"] == "passed"
    assert report["raw_rows"] == 4
    assert report["events_with_raw"] == 2
    assert report["query_plan_rows"] == 2
    assert report["coverage_num_events"] == 2
    assert not report["events_need_recollection"]
    assert (paths["output_dir"] / "raw_count_by_event.csv").exists()
    assert (paths["output_dir"] / "source_distribution.csv").exists()


def test_post_collect_qc_reports_json_read_failures(tmp_path):
    paths = write_collection(
        tmp_path,
        events=[event("E001")],
        raw_rows=[],
        plans=[plan("E001")],
        coverage={},
    )
    paths["raw"].write_text("{not json}\n", encoding="utf-8")
    paths["coverage"].write_text("[]\n", encoding="utf-8")

    code = post_collect_qc.run_qc(args(paths))

    report = read_report(paths)
    assert code == 1
    assert report["status"] == "failed"
    assert any("raw read failed" in item for item in report["failures"])
    assert any("must contain a JSON object" in item for item in report["failures"])


def test_post_collect_qc_fails_duplicates(tmp_path):
    duplicate = raw("dup", "E001", "official")
    paths = write_collection(
        tmp_path,
        events=[event("E001")],
        raw_rows=[duplicate, duplicate],
        plans=[plan("E001"), plan("E001")],
        coverage=coverage(["E001"]),
    )

    code = post_collect_qc.run_qc(args(paths, min_raw_per_event=1))

    report = read_report(paths)
    assert code == 1
    assert report["duplicate_raw_ids"] == {"dup": 2}
    assert report["duplicate_query_plan_event_ids"] == {"E001": 2}
    assert report["duplicate_raw_rows"]
    assert any("duplicate raw_id" in item for item in report["failures"])


def test_post_collect_qc_splits_required_failures_from_optional_warnings(tmp_path):
    paths = write_collection(
        tmp_path,
        events=[event("E001")],
        raw_rows=[
            {
                "event_id": "E001",
                "raw_id": "r1",
                "source": "official",
                "url": "",
                "title": "",
                "text": "",
            }
        ],
        plans=[plan("E001")],
        coverage=coverage(["E001"]),
    )

    code = post_collect_qc.run_qc(args(paths, min_raw_per_event=1))

    report = read_report(paths)
    null_report = (paths["output_dir"] / "null_field_report.csv").read_text(encoding="utf-8")
    assert code == 1
    assert any("missing required field text" in item for item in report["failures"])
    assert any("missing optional field url" in item for item in report["warnings"])
    assert any("missing optional field title" in item for item in report["warnings"])
    assert report["events_need_recollection"][0]["event_id"] == "E001"
    assert "required raw field missing" in report["events_need_recollection"][0]["reason"]
    assert "text,fail" in null_report
    assert "url,warn" in null_report


def test_post_collect_qc_marks_low_coverage_for_recollection(tmp_path):
    paths = write_collection(
        tmp_path,
        events=[event("E001")],
        raw_rows=[raw("r1", "E001", "news")],
        plans=[plan("E001")],
        coverage={
            "num_events": 1,
            "events": {
                "E001": {
                    "need_query_repair": True,
                    "missing_sources": ["official"],
                    "missing_stakeholders": ["residents"],
                    "missing_stances": [],
                    "missing_temporal_stages": ["response"],
                }
            },
        },
    )

    code = post_collect_qc.run_qc(args(paths, min_raw_per_event=15))

    report = read_report(paths)
    low_coverage_csv = (paths["output_dir"] / "low_coverage_events.csv").read_text(encoding="utf-8")
    assert code == 1
    assert report["events_need_recollection"][0]["event_id"] == "E001"
    assert "raw count below minimum" in report["events_need_recollection"][0]["reason"]
    assert "official evidence missing" in report["events_need_recollection"][0]["reason"]
    assert "coverage needs query repair" in report["events_need_recollection"][0]["reason"]
    assert "E001" in low_coverage_csv


def write_collection(tmp_path, *, events, raw_rows, plans, coverage):
    paths = {
        "events": tmp_path / "events.jsonl",
        "raw": tmp_path / "raw_posts.jsonl",
        "query_plan": tmp_path / "query_plan.jsonl",
        "coverage": tmp_path / "coverage.json",
        "output_dir": tmp_path / "post_collect_qc",
    }
    write_jsonl(paths["events"], events)
    write_jsonl(paths["raw"], raw_rows)
    write_jsonl(paths["query_plan"], plans)
    paths["coverage"].write_text(json.dumps(coverage, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths


def args(paths, min_raw_per_event=15):
    return Namespace(
        events=str(paths["events"]),
        raw=str(paths["raw"]),
        query_plan=str(paths["query_plan"]),
        coverage=str(paths["coverage"]),
        output_dir=str(paths["output_dir"]),
        min_raw_per_event=min_raw_per_event,
    )


def read_report(paths):
    return json.loads((paths["output_dir"] / "post_collect_qc_report.json").read_text(encoding="utf-8"))


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def event(event_id):
    return {"event_id": event_id, "event_name": f"{event_id} event"}


def plan(event_id):
    return {"event_id": event_id, "query_rounds": []}


def raw(raw_id, event_id, source):
    return {
        "event_id": event_id,
        "raw_id": raw_id,
        "source": source,
        "url": f"https://example.test/{raw_id}",
        "title": f"title {raw_id}",
        "text": f"text {raw_id}",
    }


def coverage(event_ids):
    return {
        "num_events": len(event_ids),
        "events": {
            event_id: {
                "need_query_repair": False,
                "missing_sources": [],
                "missing_stakeholders": [],
                "missing_stances": [],
                "missing_temporal_stages": [],
            }
            for event_id in event_ids
        },
    }
