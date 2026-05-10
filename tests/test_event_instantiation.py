from argparse import Namespace
import importlib.util
import json
from pathlib import Path

from episoa.data.loader import read_jsonl, write_jsonl
from episoa.data.validator import validate_event_instantiation_data, validate_formal_event_record, validate_paper_data


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_legacy_events_migrate_to_topic_seeds_and_clear_events(tmp_path):
    migrate = _load_script("migrate_events_to_topic_seeds.py")
    events = tmp_path / "events.jsonl"
    topics = tmp_path / "topic_seeds.jsonl"
    candidates = tmp_path / "candidate_event_instances.jsonl"
    events.write_text(
        json.dumps(
            {
                "event_id": "E001",
                "field": "field",
                "event_name": "某市旧城改造补偿争议",
                "event_description": "topic description",
                "time_window": {"start": "2025-01-01", "end": "2025-02-01"},
                "source_scope": ["news", "social_media"],
                "seed_keywords": ["旧改 补偿"],
                "stakeholder_hints": ["居民"],
                "stance_hints": ["质疑"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = migrate.migrate(
        Namespace(
            input=str(events),
            topic_output=str(topics),
            candidate_output=str(candidates),
            events_output=str(events),
            overwrite_topic_seeds=False,
            overwrite_events=False,
        )
    )

    seed = read_jsonl(topics)[0]
    assert report["status"] == "completed"
    assert seed["topic_id"] == "T001"
    assert seed["legacy_event_id"] == "E001"
    assert seed["topic_name"] == "某市旧城改造补偿争议"
    assert seed["discovery_window"] == {"start": "2025-01-01", "end": "2025-02-01"}
    assert seed["source_scope"] == ["news", "public_social"]
    assert read_jsonl(events) == []
    assert read_jsonl(candidates) == []


def test_formal_event_validator_rejects_topic_level_or_incomplete_records():
    errors = validate_formal_event_record(
        {
            "event_id": "E001",
            "topic_id": "T001",
            "event_name": "某市旧城改造补偿争议",
            "event_description": "placeholder topic",
            "time_window": {"start": "2025-01-01", "end": "2025-01-02"},
            "source_scope": ["news"],
            "queries": ["旧改"],
            "selection_status": "accepted",
            "instance_version": "v1",
        },
        "events:1",
    )

    assert any("missing location" in error for error in errors)
    assert any("missing trigger" in error for error in errors)
    assert any("missing anchor_urls" in error for error in errors)
    assert any("placeholder" in error for error in errors)


def test_accepted_candidate_promotes_and_unaccepted_candidate_does_not(tmp_path):
    promote = _load_script("promote_candidate_events.py")
    candidates = tmp_path / "candidate_event_instances.jsonl"
    output = tmp_path / "events.jsonl"
    report = tmp_path / "report.json"
    write_jsonl(
        candidates,
        [
            _candidate("CAND_T001_001", "accepted"),
            _candidate("CAND_T001_002", "rejected"),
        ],
    )

    result = promote.promote(Namespace(input=str(candidates), output=str(output), report_output=str(report)))

    events = read_jsonl(output)
    assert result["promoted_events"] == 1
    assert events[0]["event_id"] == "CAND_T001_001"
    assert events[0]["selection_status"] == "accepted"


def test_empty_events_block_paper_but_instantiation_schema_is_valid(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "raw").mkdir(parents=True)
    write_jsonl(data_dir / "topic_seeds.jsonl", [_topic_seed()])
    write_jsonl(data_dir / "candidate_event_instances.jsonl", [])
    write_jsonl(data_dir / "events.jsonl", [])
    write_jsonl(data_dir / "raw" / "raw_posts.jsonl", [])
    write_jsonl(data_dir / "evidence.jsonl", [])
    write_jsonl(data_dir / "gold_tuples.jsonl", [])
    write_jsonl(data_dir / "gold_event_chains.jsonl", [])

    instantiation = validate_event_instantiation_data(data_dir)
    paper = validate_paper_data(data_dir, outputs_dir=tmp_path / "outputs")

    assert instantiation["topic_seed_valid"] is True
    assert instantiation["formal_events_valid"] is True
    assert instantiation["formal_events_ready"] is False
    assert paper["paper_data_ready"] is False
    assert any("no accepted formal event instances" in error for error in paper["dataset"]["errors"])


def test_discovery_corpus_is_not_read_as_formal_data(tmp_path):
    data_dir = tmp_path / "data"
    discovery = data_dir / "discovery"
    (data_dir / "raw").mkdir(parents=True)
    discovery.mkdir(parents=True)
    write_jsonl(data_dir / "topic_seeds.jsonl", [_topic_seed()])
    write_jsonl(data_dir / "candidate_event_instances.jsonl", [])
    write_jsonl(data_dir / "events.jsonl", [])
    write_jsonl(data_dir / "raw" / "raw_posts.jsonl", [])
    write_jsonl(data_dir / "evidence.jsonl", [])
    write_jsonl(data_dir / "gold_tuples.jsonl", [])
    write_jsonl(data_dir / "gold_event_chains.jsonl", [])
    write_jsonl(
        discovery / "topic_evidence.jsonl",
        [{"evidence_id": "topic_ev_1", "event_id": "E001", "text": "topic evidence", "traceable": True}],
    )
    write_jsonl(
        discovery / "topic_raw_posts.jsonl",
        [{"raw_id": "topic_raw_1", "event_id": "E001", "query": "topic", "text": "topic raw"}],
    )

    paper = validate_paper_data(data_dir, outputs_dir=tmp_path / "outputs")

    assert paper["dataset"]["num_events"] == 0
    assert paper["dataset"]["num_raw_posts"] == 0
    assert paper["dataset"]["num_evidence"] == 0
    assert paper["paper_data_ready"] is False


def _topic_seed() -> dict:
    return {
        "topic_id": "T001",
        "legacy_event_id": "E001",
        "field": "field",
        "topic_name": "topic",
        "topic_description": "description",
        "discovery_window": {"start": "2025-01-01", "end": "2025-02-01"},
        "source_scope": ["news", "public_social"],
        "seed_keywords": ["keyword"],
        "stakeholder_hints": ["stakeholder"],
        "stance_hints": ["stance"],
    }


def _candidate(candidate_id: str, status: str) -> dict:
    return {
        "candidate_event_id": candidate_id,
        "topic_id": "T001",
        "candidate_event_name": "Concrete event",
        "candidate_event_description": "A concrete event in Test City",
        "location": {"province": "Test Province", "city": "Test City"},
        "time_window": {"start": "2025-01-01", "end": "2025-01-02"},
        "trigger": "official notice",
        "anchor_entities": ["Test agency"],
        "anchor_urls": ["https://source.test/event"],
        "discovery_queries": ["Concrete event Test City"],
        "source_scope": ["news", "official"],
        "candidate_status": status,
        "screening": {},
        "rejection_reason": "" if status == "accepted" else "not concrete",
        "notes": "",
    }
