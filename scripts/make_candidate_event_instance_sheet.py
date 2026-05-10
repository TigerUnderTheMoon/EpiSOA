"""Create a human screening sheet for concrete event instance discovery."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl


DEFAULT_DATA_DIR = Path("data/pubevent_soa_lite")
DEFAULT_OUTPUT = DEFAULT_DATA_DIR / "annotation" / "candidate_event_instance_sheet.csv"
FIELDS = [
    "topic_id",
    "legacy_event_id",
    "field",
    "topic_name",
    "candidate_event_id",
    "candidate_event_name",
    "candidate_event_description",
    "location_province",
    "location_city",
    "location_district",
    "location_site",
    "event_start",
    "event_end",
    "trigger",
    "anchor_entities",
    "anchor_urls",
    "discovery_queries",
    "candidate_status",
    "unique_occurrence",
    "time_anchor_present",
    "entity_anchor_present",
    "trigger_present",
    "stakeholders_identifiable",
    "public_evidence_traceable",
    "single_event_chain_feasible",
    "rejection_reason",
    "reviewer_id",
    "notes",
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = build_rows(read_jsonl(Path(args.topic_seeds)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"output": str(output), "num_topic_seed_rows": len(rows)}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a CSV template for candidate concrete event instances.")
    parser.add_argument("--topic-seeds", default=str(DEFAULT_DATA_DIR / "topic_seeds.jsonl"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser


def build_rows(topic_seeds: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for seed in topic_seeds:
        row = {field: "" for field in FIELDS}
        topic_id = str(seed.get("topic_id") or "")
        row.update(
            {
                "topic_id": topic_id,
                "legacy_event_id": str(seed.get("legacy_event_id") or ""),
                "field": str(seed.get("field") or ""),
                "topic_name": str(seed.get("topic_name") or ""),
                "candidate_event_id": f"CAND_{topic_id}_001" if topic_id else "",
                "discovery_queries": "; ".join(_as_list(seed.get("seed_keywords"))),
                "candidate_status": "new",
            }
        )
        rows.append(row)
    return rows


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


if __name__ == "__main__":
    raise SystemExit(main())
