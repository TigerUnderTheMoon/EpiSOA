import importlib.util
import json
from pathlib import Path

from episoa.data.loader import write_jsonl
from episoa.data.validator import validate_paper_data


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_validate_events_reports_empty_registry_not_ready(tmp_path):
    validate_events = _load_script("validate_events.py")
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")

    report = validate_events.validate_events(events)

    assert report == {"num_events": 0, "hard_errors": [], "events_ready": False}


def test_validate_events_rejects_incomplete_event(tmp_path):
    validate_events = _load_script("validate_events.py")
    events = tmp_path / "events.jsonl"
    write_jsonl(events, [{"event_id": "E001", "event_name": "Incomplete event"}])

    report = validate_events.validate_events(events)

    assert report["num_events"] == 1
    assert report["events_ready"] is False
    assert report["hard_errors"]


def test_formal_validator_ignores_removed_legacy_locations(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "raw").mkdir(parents=True)
    (data_dir / "interim").mkdir()
    (data_dir / "annotation").mkdir()
    write_jsonl(data_dir / "events.jsonl", [])
    write_jsonl(data_dir / "raw" / "raw_posts.jsonl", [])
    (data_dir / ("topic" + "_seeds.jsonl")).write_text(json.dumps({"legacy": True}) + "\n", encoding="utf-8")

    report = validate_paper_data(data_dir, outputs_dir=tmp_path / "outputs")

    assert report["dataset"]["num_events"] == 0
    assert report["dataset"]["num_raw_posts"] == 0
    assert report["dataset"]["num_evidence"] == 0
    assert report["paper_data_ready"] is False
