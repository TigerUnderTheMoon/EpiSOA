"""Tests for data/loader.py and data/validator.py — JSONL I/O and validation."""

import pytest

from episoa.data.loader import read_jsonl, read_typed_jsonl, write_jsonl
from episoa.data.schema import EvidenceRecord
from episoa.data.validator import (
    _contains_marker,
    _non_empty_string_list,
    _require,
    validate_formal_event_record,
    validate_paper_data,
)


# ===================================================================
# read_jsonl / write_jsonl roundtrip
# ===================================================================

@pytest.mark.unit
def test_write_and_read_roundtrip(tmp_path):
    path = tmp_path / "test.jsonl"
    records = [{"a": 1, "b": "hello"}, {"a": 2, "b": "world"}]
    write_jsonl(path, records)
    assert path.exists()
    loaded = read_jsonl(path)
    assert loaded == records


@pytest.mark.unit
def test_write_jsonl_empty_list(tmp_path):
    path = tmp_path / "empty.jsonl"
    write_jsonl(path, [])
    assert path.exists()
    loaded = read_jsonl(path)
    assert loaded == []


@pytest.mark.unit
def test_read_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "with_blanks.jsonl"
    path.write_text('{"a":1}\n\n{"a":2}\n  \n{"a":3}\n', encoding="utf-8")
    loaded = read_jsonl(path)
    assert len(loaded) == 3


@pytest.mark.unit
def test_read_jsonl_missing_file():
    with pytest.raises(FileNotFoundError):
        read_jsonl("nonexistent_file.jsonl")


@pytest.mark.unit
def test_read_jsonl_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"a":1}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_jsonl(path)


@pytest.mark.unit
def test_read_jsonl_non_object(tmp_path):
    path = tmp_path / "non_object.jsonl"
    path.write_text('{"a":1}\n[1,2,3]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        read_jsonl(path)


@pytest.mark.unit
def test_write_jsonl_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "sub" / "out.jsonl"
    write_jsonl(path, [{"x": 1}])
    assert path.exists()
    assert read_jsonl(path)[0]["x"] == 1


# ===================================================================
# read_typed_jsonl
# ===================================================================

@pytest.mark.unit
def test_read_typed_jsonl_valid(tmp_path):
    path = tmp_path / "evidence.jsonl"
    write_jsonl(path, [
        {"evidence_id": "ev-1", "event_id": "E001", "text": "test", "url": "https://a.com"},
        {"evidence_id": "ev-2", "event_id": "E001", "text": "test2", "url": "https://b.com"},
    ])
    records = read_typed_jsonl(path, EvidenceRecord)
    assert len(records) == 2
    assert records[0].evidence_id == "ev-1"
    assert isinstance(records[0], EvidenceRecord)


@pytest.mark.unit
def test_read_typed_jsonl_invalid(tmp_path):
    path = tmp_path / "bad_schema.jsonl"
    write_jsonl(path, [{"evidence_id": "ev-1", "event_id": "E001"}])  # missing text, url
    with pytest.raises(ValueError, match="schema validation"):
        read_typed_jsonl(path, EvidenceRecord)


# ===================================================================
# validate_formal_event_record
# ===================================================================

EVENT_MINIMAL = {
    "event_id": "E001",
    "domain": "urban_renewal",
    "event_type": "concrete_event",
    "event_name": "Test Event",
    "event_description": "A test concrete event for validation",
    "location": {"province": "Guangdong", "city": "Shenzhen"},
    "time_window": {"start": "2025-01-01", "end": "2025-01-15"},
    "trigger": "Public report of incident",
    "anchor_entities": {"gov": "City Government"},
    "anchor_urls": ["https://example.com/news"],
    "source_scope": ["news"],
    "query_seeds": ["test event seeds"],
    "stakeholder_hints": ["Residents", "Government"],
    "stance_hints": ["concern", "response"],
    "temporal_stages": ["trigger", "response"],
}


@pytest.mark.unit
def test_valid_event_record():
    errors = validate_formal_event_record(EVENT_MINIMAL)
    assert errors == []


@pytest.mark.unit
def test_event_missing_required_field():
    bad = dict(EVENT_MINIMAL)
    del bad["event_name"]
    errors = validate_formal_event_record(bad)
    assert any("missing event_name" in e for e in errors)


@pytest.mark.unit
def test_event_missing_time_window():
    bad = dict(EVENT_MINIMAL)
    bad["time_window"] = {}
    errors = validate_formal_event_record(bad)
    assert any("missing factual time_window" in e for e in errors)


@pytest.mark.unit
def test_event_empty_stakeholder_hints():
    bad = dict(EVENT_MINIMAL)
    bad["stakeholder_hints"] = []
    errors = validate_formal_event_record(bad)
    assert any("stakeholder_hints" in e for e in errors)


@pytest.mark.unit
def test_event_social_media_in_source_scope():
    bad = dict(EVENT_MINIMAL)
    bad["source_scope"] = ["social_media", "news"]
    errors = validate_formal_event_record(bad)
    assert any("social_media" in e for e in errors)


@pytest.mark.unit
def test_event_bad_anchor_entities():
    bad = dict(EVENT_MINIMAL)
    bad["anchor_entities"] = {"": "empty key"}
    errors = validate_formal_event_record(bad)
    assert any("empty role key" in e for e in errors)


# ===================================================================
# _require
# ===================================================================

@pytest.mark.unit
def test_require_all_present():
    errors: list[str] = []
    _require({"a": 1, "b": 2}, ["a", "b"], "test", errors)
    assert errors == []


@pytest.mark.unit
def test_require_missing_key():
    errors: list[str] = []
    _require({"a": 1}, ["a", "b"], "test", errors)
    assert any("missing b" in e for e in errors)


@pytest.mark.unit
def test_require_empty_string():
    errors: list[str] = []
    _require({"a": ""}, ["a"], "test", errors)
    assert any("missing a" in e for e in errors)


# ===================================================================
# _non_empty_string_list
# ===================================================================

@pytest.mark.unit
def test_non_empty_string_list_valid():
    assert _non_empty_string_list(["a", "b"]) is True


@pytest.mark.unit
def test_non_empty_string_list_empty():
    assert _non_empty_string_list([]) is False


@pytest.mark.unit
def test_non_empty_string_list_not_list():
    assert _non_empty_string_list("string") is False


@pytest.mark.unit
def test_non_empty_string_list_contains_empty():
    assert _non_empty_string_list(["a", ""]) is False


# ===================================================================
# _contains_marker
# ===================================================================

@pytest.mark.unit
def test_contains_marker_in_string():
    assert _contains_marker("this is a mock test") is True
    assert _contains_marker("this is real data") is False


@pytest.mark.unit
def test_contains_marker_in_nested():
    assert _contains_marker({"text": "some sample data"}) is True
    assert _contains_marker({"text": "real data"}) is False


# ===================================================================
# validate_paper_data (integration-light: uses real data/)
# ===================================================================

@pytest.mark.unit
def test_validate_paper_data_reports_missing_dir(tmp_path):
    result = validate_paper_data(data_dir=tmp_path / "nonexistent", outputs_dir=tmp_path / "out")
    assert not result["paper_data_ready"]
    assert len(result["dataset"]["errors"]) > 0


@pytest.mark.unit
def test_validate_paper_data_empty_dir(tmp_path):
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    result = validate_paper_data(data_dir=tmp_path, outputs_dir=tmp_path / "out")
    assert not result["paper_data_ready"]
    assert any("events.jsonl" in e for e in result["dataset"]["errors"])
