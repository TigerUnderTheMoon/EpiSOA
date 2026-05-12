from argparse import Namespace
import csv
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "residual_failure_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("residual_failure_diagnostics_script", SCRIPT_PATH)
diagnostics_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(diagnostics_script)


def test_residual_diagnostics_writes_failure_candidates_and_provider_errors(tmp_path):
    events = tmp_path / "events.jsonl"
    run_dir = tmp_path / "run"
    output_dir = run_dir / "residual_diagnostics"
    (run_dir / "post_collect_qc").mkdir(parents=True)
    event = {
        "event_id": "E001",
        "event_name": "test event",
        "source_scope": ["news"],
        "temporal_stages": ["trigger", "conflict", "response"],
    }
    raw = {
        "raw_id": "r1",
        "event_id": "E001",
        "source": "news",
        "source_type": "news",
        "requested_source_type": "news",
        "url": "https://people.com.cn/a",
        "title": "居民反映公共空间被占用",
        "snippet": "相关部门表示已受理",
        "text": "居民反映公共空间被占用，相关部门表示已受理。",
    }
    events.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "raw_posts.jsonl").write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "coverage.json").write_text(
        json.dumps(
            {
                "events": {"E001": {}},
                "errors": [
                    {
                        "event_id": "E001",
                        "query": "q",
                        "source_type": "news",
                        "provider": "custom",
                        "error_type": "TimeoutException",
                        "duration_seconds": 1.2,
                        "retry_count": 2,
                        "final_status": "failed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "repair_collection_summary.json").write_text('{"events":{}}\n', encoding="utf-8")
    (run_dir / "post_collect_qc" / "post_collect_qc_report.json").write_text(
        json.dumps(
            {
                "events_need_recollection": [
                    {
                        "event_id": "E001",
                        "raw_count": 1,
                        "reason": "raw count below minimum; coverage missing stances",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    code = diagnostics_script.main(
        [
            "--run-dir",
            str(run_dir),
            "--events",
            str(events),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert code == 0
    summary = list(csv.DictReader((output_dir / "failed_events_summary.csv").open(encoding="utf-8")))
    stance_candidates = list(csv.DictReader((output_dir / "missing_stance_candidates.csv").open(encoding="utf-8")))
    provider_errors = list(csv.DictReader((output_dir / "provider_error_summary.csv").open(encoding="utf-8")))
    matrix = list(csv.DictReader((output_dir / "event_raw_coverage_matrix.csv").open(encoding="utf-8")))
    assert summary[0]["event_id"] == "E001"
    assert summary[0]["suspected_failure_type"] == "provider_instability"
    assert stance_candidates and stance_candidates[0]["possible_stance_keywords"]
    assert provider_errors[0]["error_type"] == "TimeoutException"
    assert matrix[0]["covered_stances"]
