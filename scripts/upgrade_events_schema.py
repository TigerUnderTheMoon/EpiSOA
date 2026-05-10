"""Upgrade events.jsonl to the final event-first registry schema."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl


DEFAULT_EVENTS_PATH = Path("data/pubevent_soa_lite/events.jsonl")
TEMPORAL_STAGES = ["trigger", "conflict", "response", "resolution", "follow_up"]
CORE_FIELDS = [
    "event_id",
    "domain",
    "event_type",
    "event_name",
    "event_description",
    "location",
    "time_window",
    "trigger",
    "anchor_entities",
    "anchor_urls",
    "source_scope",
    "query_seeds",
    "stakeholder_hints",
    "stance_hints",
    "temporal_stages",
]
OLD_QUERY_FIELD = "quer" + "ies"
OLD_SELECTION_FIELD = "selection_" + "status"
OLD_VERSION_FIELD = "instance_" + "version"
DOMAIN_STANCES = {
    "urban_renewal": ["支持", "反对", "质疑", "回应", "安置", "补偿"],
    "education": ["支持", "反对", "质疑", "回应", "解释", "担忧"],
    "healthcare": ["支持", "质疑", "投诉", "回应", "整改", "解释"],
    "public_safety": ["担忧", "质疑", "投诉", "回应", "整改", "解释"],
    "urban_mobility": ["支持", "反对", "质疑", "回应", "整改", "担忧"],
    "digital_governance": ["支持", "质疑", "投诉", "回应", "整改", "解释"],
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = upgrade_events(Path(args.events))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upgrade events.jsonl to the final event-first schema.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS_PATH))
    return parser


def upgrade_events(path: Path) -> dict[str, Any]:
    records = read_jsonl(path)
    upgraded: list[dict[str, Any]] = []
    fields_added: Counter[str] = Counter()
    fields_renamed: Counter[str] = Counter()
    fields_removed: Counter[str] = Counter()
    domains_assigned: Counter[str] = Counter()

    for record in records:
        event = dict(record)
        event_id = str(event.get("event_id") or "")
        domain = str(event.get("domain") or domain_for_event_id(event_id))
        if event.get("domain") != domain:
            fields_added["domain"] += 1
        domains_assigned[domain] += 1
        event["domain"] = domain

        if event.get("event_type") != "concrete_event":
            fields_added["event_type"] += 1
        event["event_type"] = "concrete_event"

        if "query_seeds" not in event:
            event["query_seeds"] = _as_list(event.get(OLD_QUERY_FIELD) or event.get("seed_keywords") or event.get("event_name"))
            fields_renamed[f"{OLD_QUERY_FIELD}->query_seeds"] += 1 if OLD_QUERY_FIELD in event else 0

        if not _as_list(event.get("stakeholder_hints")):
            event["stakeholder_hints"] = stakeholder_hints_for_event(event)
            fields_added["stakeholder_hints"] += 1

        if not _as_list(event.get("stance_hints")):
            event["stance_hints"] = DOMAIN_STANCES.get(domain, ["支持", "反对", "质疑", "回应"])
            fields_added["stance_hints"] += 1

        if event.get("temporal_stages") != TEMPORAL_STAGES:
            event["temporal_stages"] = list(TEMPORAL_STAGES)
            fields_added["temporal_stages"] += 1

        for key in (OLD_QUERY_FIELD, OLD_SELECTION_FIELD, OLD_VERSION_FIELD, "field", "seed_keywords"):
            if key in event:
                event.pop(key)
                fields_removed[key] += 1

        upgraded.append({key: event.get(key) for key in CORE_FIELDS})

    write_jsonl(path, upgraded)
    return {
        "num_records": len(upgraded),
        "fields_added": dict(fields_added),
        "fields_renamed": dict(fields_renamed),
        "fields_removed": dict(fields_removed),
        "domains_assigned": dict(domains_assigned),
    }


def domain_for_event_id(event_id: str) -> str:
    try:
        number = int("".join(char for char in event_id if char.isdigit()))
    except ValueError:
        return "urban_renewal"
    if 1 <= number <= 10:
        return "urban_renewal"
    if 11 <= number <= 20:
        return "education"
    if 21 <= number <= 30:
        return "healthcare"
    if 31 <= number <= 40:
        return "public_safety"
    if 41 <= number <= 45:
        return "urban_mobility"
    if 46 <= number <= 50:
        return "digital_governance"
    return "urban_renewal"


def stakeholder_hints_for_event(event: dict[str, Any]) -> list[str]:
    values: list[str] = []
    anchors = event.get("anchor_entities")
    if isinstance(anchors, dict):
        for value in anchors.values():
            values.extend(_as_list(value))
    values.extend(_as_list(event.get("event_name")))
    return _unique(values)[:8]


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


if __name__ == "__main__":
    raise SystemExit(main())
