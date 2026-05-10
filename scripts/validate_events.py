"""Validate the formal PubEvent-SOA event registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from episoa.data.loader import read_jsonl
from episoa.data.validator import validate_formal_event_record


DEFAULT_EVENTS_PATH = Path("data/pubevent_soa_lite/events.jsonl")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_events(Path(args.events))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["hard_errors"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate accepted concrete public events.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS_PATH))
    return parser


def validate_events(path: Path) -> dict:
    hard_errors: list[str] = []
    try:
        events = read_jsonl(path)
    except (FileNotFoundError, ValueError) as exc:
        events = []
        hard_errors.append(str(exc))

    for index, event in enumerate(events, start=1):
        hard_errors.extend(validate_formal_event_record(event, f"events:{index}"))

    return {
        "num_events": len(events),
        "hard_errors": hard_errors,
        "events_ready": bool(events) and not hard_errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
