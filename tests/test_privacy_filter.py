import json
import importlib.util
from pathlib import Path
from uuid import uuid4

from episoa.preprocess.privacy_filter import PrivacyFilterStats, clean_raw_evidence
from episoa.schemas.evidence import EvidenceRecord


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_semireal_dataset.py"
SPEC = importlib.util.spec_from_file_location("prepare_semireal_dataset", SCRIPT_PATH)
prepare_semireal_dataset = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(prepare_semireal_dataset)
prepare_dataset = prepare_semireal_dataset.prepare_dataset


def test_clean_raw_evidence_removes_direct_identifiers() -> None:
    stats = PrivacyFilterStats()
    raw = {
        "evidence_id": "raw-1",
        "event_id": "evt-1",
        "platform": "Public Forum",
        "url": "https://example.org/public/thread",
        "timestamp": "2026-02-01T10:00:00Z",
        "text": "Contact jane@example.org or 555-123-4567; sample ID 110105199901012345.",
        "author_name": "Jane Example",
        "author_profile_url": "https://example.org/users/jane",
        "source_type": "forum",
        "metadata": {
            "stakeholder": "residents",
            "author_homepage": "https://example.org/users/jane",
            "moderator_phone": "555-123-4567",
        },
    }

    cleaned = clean_raw_evidence(raw, stats)
    record = EvidenceRecord.model_validate(cleaned)

    assert record.author_alias.startswith("author_")
    assert "Jane Example" not in json.dumps(cleaned)
    assert "jane@example.org" not in record.text
    assert "555-123-4567" not in json.dumps(cleaned)
    assert "110105199901012345" not in record.text
    assert "author_homepage" not in record.metadata
    assert "moderator_phone" not in record.metadata
    assert record.metadata["event_id"] == "evt-1"
    assert stats.profile_urls_removed == 2


def test_prepare_semireal_dataset_writes_clean_jsonl_and_report() -> None:
    work_dir = Path("outputs/test_tmp/privacy_filter") / uuid4().hex
    raw_path = work_dir / "evidence_raw.jsonl"
    clean_path = work_dir / "evidence_clean.jsonl"
    report_path = work_dir / "cleaning_report.json"
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(
            {
                "evidence_id": "raw-1",
                "event_id": "evt-1",
                "platform": "Public News",
                "url": "https://example.org/news/item",
                "timestamp": "2026-02-01T10:00:00Z",
                "text": "Public comment included contact a@example.org.",
                "author_username": "@public_user",
                "author_profile_url": "https://example.org/users/public-user",
                "source_type": "news",
                "metadata": {"stakeholder": "residents"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = prepare_dataset(input_path=raw_path, output_path=clean_path, report_path=report_path)
    rows = [json.loads(line) for line in clean_path.read_text(encoding="utf-8").splitlines()]

    assert report["cleaned_records"] == 1
    assert clean_path.exists()
    assert report_path.exists()
    assert rows[0]["author_alias"].startswith("author_")
    assert "a@example.org" not in rows[0]["text"]
