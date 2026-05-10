"""Promote accepted candidate concrete events into formal events.jsonl."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl
from episoa.data.validator import validate_candidate_for_promotion


DEFAULT_DATA_DIR = Path("data/pubevent_soa_lite")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = promote(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["hard_errors"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote accepted candidate event instances into formal events.jsonl.")
    parser.add_argument("--input", default=str(DEFAULT_DATA_DIR / "candidate_event_instances.jsonl"))
    parser.add_argument("--output", default=str(DEFAULT_DATA_DIR / "events.jsonl"))
    parser.add_argument("--report-output", default=str(DEFAULT_DATA_DIR / "interim" / "event_promotion_report.json"))
    return parser


def promote(args: argparse.Namespace) -> dict[str, Any]:
    candidates = read_jsonl(Path(args.input)) if Path(args.input).exists() else []
    accepted = [candidate for candidate in candidates if candidate.get("candidate_status") == "accepted"]
    events: list[dict[str, Any]] = []
    hard_errors: list[str] = []
    for index, candidate in enumerate(accepted, start=1):
        label = f"accepted_candidate:{index}"
        errors = validate_candidate_for_promotion(candidate, label)
        if errors:
            hard_errors.extend(errors)
            continue
        events.append(candidate_to_event(candidate))

    if not hard_errors:
        write_jsonl(Path(args.output), events)
    report = {
        "num_candidates": len(candidates),
        "accepted_candidates": len(accepted),
        "promoted_events": len(events) if not hard_errors else 0,
        "skipped_not_accepted": len(candidates) - len(accepted),
        "hard_errors": hard_errors,
    }
    report_path = Path(args.report_output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def candidate_to_event(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": candidate["candidate_event_id"],
        "topic_id": candidate["topic_id"],
        "event_name": candidate["candidate_event_name"],
        "event_description": candidate["candidate_event_description"],
        "location": candidate["location"],
        "time_window": candidate["time_window"],
        "trigger": candidate["trigger"],
        "anchor_entities": candidate["anchor_entities"],
        "anchor_urls": candidate["anchor_urls"],
        "source_scope": candidate["source_scope"],
        "queries": candidate["discovery_queries"],
        "selection_status": "accepted",
        "instance_version": str(candidate.get("instance_version") or "v1"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
