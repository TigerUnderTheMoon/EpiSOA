"""Migrate legacy topic-level events into topic_seeds.jsonl."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl


DEFAULT_DATA_DIR = Path("data/pubevent_soa_lite")
SOURCE_ALIASES = {"social_media": "public_social"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = migrate(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"completed", "noop"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate legacy events.jsonl topic templates into topic_seeds.jsonl.")
    parser.add_argument("--input", default=str(DEFAULT_DATA_DIR / "events.jsonl"))
    parser.add_argument("--topic-output", default=str(DEFAULT_DATA_DIR / "topic_seeds.jsonl"))
    parser.add_argument("--candidate-output", default=str(DEFAULT_DATA_DIR / "candidate_event_instances.jsonl"))
    parser.add_argument("--events-output", default=str(DEFAULT_DATA_DIR / "events.jsonl"))
    parser.add_argument("--overwrite-topic-seeds", action="store_true")
    parser.add_argument("--overwrite-events", action="store_true")
    return parser


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input)
    topic_output = Path(args.topic_output)
    candidate_output = Path(args.candidate_output)
    events_output = Path(args.events_output)

    legacy_events = read_jsonl(input_path) if input_path.exists() else []
    if not legacy_events and topic_output.exists():
        if not candidate_output.exists():
            write_jsonl(candidate_output, [])
        if not events_output.exists():
            write_jsonl(events_output, [])
        return {"status": "noop", "reason": "events input is empty and topic_seeds.jsonl already exists"}

    if topic_output.exists() and not args.overwrite_topic_seeds:
        existing_topics = read_jsonl(topic_output)
        if existing_topics:
            if _contains_formal_events(legacy_events) and not args.overwrite_events:
                return {"status": "blocked", "reason": "events input appears to contain formal event data"}
            write_jsonl(events_output, [])
            if not candidate_output.exists():
                write_jsonl(candidate_output, [])
            return {
                "status": "noop",
                "reason": "topic_seeds.jsonl already exists; kept existing topic seed data",
                "num_topic_seeds": len(existing_topics),
            }

    topic_seeds = [convert_legacy_event(record, index) for index, record in enumerate(legacy_events, start=1)]
    write_jsonl(topic_output, topic_seeds)
    if not candidate_output.exists():
        write_jsonl(candidate_output, [])
    if legacy_events and not _contains_formal_events(legacy_events):
        write_jsonl(events_output, [])
    elif args.overwrite_events:
        write_jsonl(events_output, [])
    else:
        return {"status": "blocked", "reason": "events input appears to contain formal event data"}

    return {
        "status": "completed",
        "num_legacy_events_read": len(legacy_events),
        "num_topic_seeds_written": len(topic_seeds),
        "events_output_cleared": True,
        "candidate_event_instances_initialized": candidate_output.exists(),
    }


def convert_legacy_event(record: dict[str, Any], index: int) -> dict[str, Any]:
    legacy_event_id = str(record.get("event_id") or f"E{index:03d}")
    topic_id = _topic_id_from_legacy(legacy_event_id, index)
    return {
        "topic_id": topic_id,
        "legacy_event_id": legacy_event_id,
        "field": record.get("field"),
        "topic_name": record.get("event_name") or "",
        "topic_description": record.get("event_description") or "",
        "discovery_window": record.get("time_window"),
        "source_scope": _normalize_sources(record.get("source_scope")),
        "seed_keywords": _as_list(record.get("seed_keywords")),
        "stakeholder_hints": _as_list(record.get("stakeholder_hints")),
        "stance_hints": _as_list(record.get("stance_hints")),
    }


def _topic_id_from_legacy(legacy_event_id: str, index: int) -> str:
    digits = "".join(char for char in legacy_event_id if char.isdigit())
    return f"T{int(digits):03d}" if digits else f"T{index:03d}"


def _normalize_sources(value: Any) -> list[str]:
    return _unique([SOURCE_ALIASES.get(item.lower(), item) for item in _as_list(value)])


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item not in seen:
            output.append(item)
            seen.add(item)
    return output


def _contains_formal_events(records: list[dict[str, Any]]) -> bool:
    return any(record.get("topic_id") and record.get("selection_status") for record in records)


if __name__ == "__main__":
    raise SystemExit(main())
