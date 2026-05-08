"""Validation for the PubEvent-SOA paper dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl

DATA_DIR = Path("data/pubevent_soa_lite")
REQUIRED_FILES = {
    "events": DATA_DIR / "events.jsonl",
    "raw_posts": DATA_DIR / "raw" / "raw_posts.jsonl",
    "evidence": DATA_DIR / "evidence.jsonl",
    "gold_tuples": DATA_DIR / "gold_tuples.jsonl",
    "gold_event_chains": DATA_DIR / "gold_event_chains.jsonl",
}
MOCK_MARKERS = ("mock", "sample", "demo", "fictional", "example.org")


def validate_paper_data(data_dir: str | Path = DATA_DIR, outputs_dir: str | Path = "outputs") -> dict[str, Any]:
    data_dir = Path(data_dir)
    outputs_dir = Path(outputs_dir)
    paths = {
        "events": data_dir / "events.jsonl",
        "raw_posts": data_dir / "raw" / "raw_posts.jsonl",
        "evidence": data_dir / "evidence.jsonl",
        "gold_tuples": data_dir / "gold_tuples.jsonl",
        "gold_event_chains": data_dir / "gold_event_chains.jsonl",
    }
    errors: list[str] = []
    warnings: list[str] = []
    records: dict[str, list[dict[str, Any]]] = {}

    for name, path in paths.items():
        if not path.exists():
            errors.append(f"missing required data file: {path}")
            records[name] = []
            continue
        try:
            records[name] = read_jsonl(path)
        except ValueError as exc:
            errors.append(str(exc))
            records[name] = []
        if path.exists() and not records[name]:
            errors.append(f"{path} is empty")

    events = records.get("events", [])
    raw_posts = records.get("raw_posts", [])
    evidence = records.get("evidence", [])
    gold_tuples = records.get("gold_tuples", [])
    gold_event_chains = records.get("gold_event_chains", [])
    event_ids = {item.get("event_id") for item in events if isinstance(item.get("event_id"), str)}
    evidence_ids = {item.get("evidence_id") for item in evidence if isinstance(item.get("evidence_id"), str)}

    for index, event in enumerate(events, start=1):
        _require(event, ["event_id"], f"events:{index}", errors)
        if not (event.get("event_name") or event.get("event_description")):
            errors.append(f"events:{index} missing event_name or event_description")

    for index, item in enumerate(raw_posts, start=1):
        _require(
            item,
            ["raw_id", "event_id", "query", "source", "platform", "text", "collected_at"],
            f"raw_posts:{index}",
            errors,
        )
        if not (item.get("publish_time") or item.get("url")):
            errors.append(f"raw_posts:{index} missing publish_time or url")
        if item.get("event_id") not in event_ids:
            errors.append(f"raw_posts:{index} references unknown event_id: {item.get('event_id')!r}")

    for index, item in enumerate(evidence, start=1):
        _require(item, ["evidence_id", "event_id", "text"], f"evidence:{index}", errors)
        if not (item.get("source") or item.get("platform")):
            errors.append(f"evidence:{index} missing source/platform")
        if not (item.get("publish_time") or item.get("url")):
            errors.append(f"evidence:{index} missing publish_time or url")
        if "traceable" not in item:
            errors.append(f"evidence:{index} missing traceable")
        if item.get("event_id") not in event_ids:
            errors.append(f"evidence:{index} references unknown event_id: {item.get('event_id')!r}")

    if not raw_posts and not evidence:
        errors.append("no collected evidence found; run scripts/collect_evidence.py and scripts/normalize_evidence.py before annotation")
    elif raw_posts and not evidence:
        errors.append("raw posts exist but evidence.jsonl is empty; run scripts/normalize_evidence.py before annotation")

    if (gold_tuples or gold_event_chains) and not evidence:
        errors.append("gold annotations exist but evidence.jsonl is missing or empty; do not create gold before normalized evidence")

    for index, item in enumerate(gold_tuples, start=1):
        _require(
            item,
            ["event_id", "stakeholder", "opinion", "sentiment", "rationale", "evidence_ids", "support_label"],
            f"gold_tuples:{index}",
            errors,
        )
        if item.get("event_id") not in event_ids:
            errors.append(f"gold_tuples:{index} references unknown event_id: {item.get('event_id')!r}")
        for evidence_id in item.get("evidence_ids", []) if isinstance(item.get("evidence_ids"), list) else []:
            if evidence_id not in evidence_ids:
                errors.append(f"gold_tuples:{index} references unknown evidence_id: {evidence_id!r}")

    for index, item in enumerate(gold_event_chains, start=1):
        _require(item, ["event_id", "evidence_ids"], f"gold_event_chains:{index}", errors)
        if not (item.get("event_chain") or item.get("chain_nodes")):
            errors.append(f"gold_event_chains:{index} missing event_chain or chain_nodes")
        if item.get("event_id") not in event_ids:
            errors.append(f"gold_event_chains:{index} references unknown event_id: {item.get('event_id')!r}")
        for evidence_id in item.get("evidence_ids", []) if isinstance(item.get("evidence_ids"), list) else []:
            if evidence_id not in evidence_ids:
                errors.append(f"gold_event_chains:{index} references unknown evidence_id: {evidence_id!r}")

    scattered = [
        path
        for pattern in ("*.json", "*.jsonl", "*.csv")
        for path in Path("data").glob(pattern)
        if path.is_file()
    ]
    if scattered:
        errors.append("scattered data files found at data root: " + ", ".join(str(path) for path in scattered))

    if _contains_marker([*events, *evidence, *gold_tuples, *gold_event_chains]):
        errors.append("paper data contains mock/sample/demo/fictional/example.org marker text")

    historical_outputs = [
        path
        for pattern in ("*.json", "*.jsonl", "*.csv", "*.txt")
        for path in outputs_dir.glob(pattern)
        if path.name not in {"README.md"}
    ]
    if historical_outputs:
        warnings.append("historical output files found: " + ", ".join(str(path) for path in historical_outputs))

    return {
        "paper_data_ready": not errors,
        "dataset": {
            "is_formal_dataset": not errors,
            "num_events": len(events),
            "num_raw_posts": len(raw_posts),
            "num_evidence": len(evidence),
            "num_gold_tuples": len(gold_tuples),
            "num_gold_event_chains": len(gold_event_chains),
            "errors": errors,
            "warnings": warnings,
        },
    }


def _require(record: dict[str, Any], keys: list[str], label: str, errors: list[str]) -> None:
    for key in keys:
        value = record.get(key)
        if value in (None, "", []):
            errors.append(f"{label} missing {key}")


def _contains_marker(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in MOCK_MARKERS)
    if isinstance(value, dict):
        return any(_contains_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_marker(item) for item in value)
    return False
