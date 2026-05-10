"""Validation for the PubEvent-SOA paper dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl
from episoa.data.schema import CandidateEventInstance, EventRecord, TopicSeedRecord

DATA_DIR = Path("data/pubevent_soa_lite")
REQUIRED_FILES = {
    "events": DATA_DIR / "events.jsonl",
    "raw_posts": DATA_DIR / "raw" / "raw_posts.jsonl",
    "evidence": DATA_DIR / "evidence.jsonl",
    "gold_tuples": DATA_DIR / "gold_tuples.jsonl",
    "gold_event_chains": DATA_DIR / "gold_event_chains.jsonl",
}
MOCK_MARKERS = ("mock", "sample", "demo", "fictional", "example.org")
PLACEHOLDER_MARKERS = ("某市", "某地", "某校", "某医院", "某平台")
SOURCE_ALIASES = {"social_media": "public_social"}
SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}
SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "insufficient_evidence"}


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
        if path.exists() and not records[name] and name != "events":
            errors.append(f"{path} is empty")

    events = records.get("events", [])
    raw_posts = records.get("raw_posts", [])
    evidence = records.get("evidence", [])
    gold_tuples = records.get("gold_tuples", [])
    gold_event_chains = records.get("gold_event_chains", [])
    event_ids = {item.get("event_id") for item in events if isinstance(item.get("event_id"), str)}
    evidence_ids = {item.get("evidence_id") for item in evidence if isinstance(item.get("evidence_id"), str)}
    evidence_event_ids = {
        item.get("evidence_id"): item.get("event_id")
        for item in evidence
        if isinstance(item.get("evidence_id"), str) and isinstance(item.get("event_id"), str)
    }

    if not events:
        errors.append(
            "no accepted formal event instances found; complete topic-to-event instantiation before evidence collection"
        )
    for index, event in enumerate(events, start=1):
        errors.extend(validate_formal_event_record(event, f"events:{index}"))

    skip_event_references = not event_ids

    for index, item in enumerate(raw_posts, start=1):
        _require(
            item,
            ["raw_id", "event_id", "query", "source", "platform", "text", "collected_at"],
            f"raw_posts:{index}",
            errors,
        )
        if not (item.get("publish_time") or item.get("url")):
            errors.append(f"raw_posts:{index} missing publish_time or url")
        if not skip_event_references and item.get("event_id") not in event_ids:
            errors.append(f"raw_posts:{index} references unknown event_id: {item.get('event_id')!r}")

    for index, item in enumerate(evidence, start=1):
        _require(item, ["evidence_id", "event_id", "text"], f"evidence:{index}", errors)
        if not (item.get("source") or item.get("platform")):
            errors.append(f"evidence:{index} missing source/platform")
        if not (item.get("publish_time") or item.get("url")):
            errors.append(f"evidence:{index} missing publish_time or url")
        if "traceable" not in item:
            errors.append(f"evidence:{index} missing traceable")
        if not skip_event_references and item.get("event_id") not in event_ids:
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
        if not skip_event_references and item.get("event_id") not in event_ids:
            errors.append(f"gold_tuples:{index} references unknown event_id: {item.get('event_id')!r}")
        if item.get("sentiment") not in SENTIMENTS:
            errors.append(f"gold_tuples:{index} has invalid sentiment: {item.get('sentiment')!r}")
        if item.get("support_label") not in SUPPORT_LABELS:
            errors.append(f"gold_tuples:{index} has invalid support_label: {item.get('support_label')!r}")
        for evidence_id in item.get("evidence_ids", []) if isinstance(item.get("evidence_ids"), list) else []:
            if evidence_id not in evidence_ids:
                errors.append(f"gold_tuples:{index} references unknown evidence_id: {evidence_id!r}")
            elif not skip_event_references and evidence_event_ids.get(evidence_id) != item.get("event_id"):
                errors.append(f"gold_tuples:{index} references evidence_id from another event: {evidence_id!r}")

    for index, item in enumerate(gold_event_chains, start=1):
        _require(item, ["event_id", "evidence_ids"], f"gold_event_chains:{index}", errors)
        if not (item.get("event_chain") or item.get("chain_nodes")):
            errors.append(f"gold_event_chains:{index} missing event_chain or chain_nodes")
        if not skip_event_references and item.get("event_id") not in event_ids:
            errors.append(f"gold_event_chains:{index} references unknown event_id: {item.get('event_id')!r}")
        for evidence_id in item.get("evidence_ids", []) if isinstance(item.get("evidence_ids"), list) else []:
            if evidence_id not in evidence_ids:
                errors.append(f"gold_event_chains:{index} references unknown evidence_id: {evidence_id!r}")
            elif not skip_event_references and evidence_event_ids.get(evidence_id) != item.get("event_id"):
                errors.append(f"gold_event_chains:{index} references evidence_id from another event: {evidence_id!r}")

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


def validate_event_instantiation_data(data_dir: str | Path = DATA_DIR) -> dict[str, Any]:
    data_dir = Path(data_dir)
    paths = {
        "topic_seeds": data_dir / "topic_seeds.jsonl",
        "candidate_event_instances": data_dir / "candidate_event_instances.jsonl",
        "events": data_dir / "events.jsonl",
    }
    hard_errors: list[str] = []
    warnings: list[str] = []
    records: dict[str, list[dict[str, Any]]] = {}

    for name, path in paths.items():
        if not path.exists():
            if name == "topic_seeds":
                hard_errors.append(f"missing required data file: {path}")
            records[name] = []
            continue
        try:
            records[name] = read_jsonl(path)
        except ValueError as exc:
            hard_errors.append(str(exc))
            records[name] = []

    topic_seeds = records["topic_seeds"]
    candidates = records["candidate_event_instances"]
    formal_events = records["events"]
    topic_ids: set[str] = set()

    for index, seed in enumerate(topic_seeds, start=1):
        label = f"topic_seeds:{index}"
        try:
            TopicSeedRecord.model_validate(seed)
        except Exception as exc:  # pydantic error text is useful in the report
            hard_errors.append(f"{label} schema error: {exc}")
            continue
        topic_id = str(seed.get("topic_id", ""))
        topic_ids.add(topic_id)
        if "social_media" in [str(item) for item in seed.get("source_scope", [])]:
            hard_errors.append(f"{label} source_scope uses social_media; use public_social")

    for index, candidate in enumerate(candidates, start=1):
        label = f"candidate_event_instances:{index}"
        try:
            CandidateEventInstance.model_validate(candidate)
        except Exception as exc:
            hard_errors.append(f"{label} schema error: {exc}")
            continue
        if candidate.get("topic_id") not in topic_ids:
            hard_errors.append(f"{label} references unknown topic_id: {candidate.get('topic_id')!r}")
        if candidate.get("candidate_status") == "accepted":
            hard_errors.extend(validate_candidate_for_promotion(candidate, label))

    for index, event in enumerate(formal_events, start=1):
        label = f"events:{index}"
        hard_errors.extend(validate_formal_event_record(event, label))
        if event.get("topic_id") not in topic_ids:
            hard_errors.append(f"{label} references unknown topic_id: {event.get('topic_id')!r}")

    if not topic_seeds:
        hard_errors.append("topic_seeds.jsonl is empty")
    if not formal_events:
        warnings.append("formal_events_ready=false: no accepted formal event instances found")

    topic_seed_valid = not any(error.startswith("topic_seeds:") or "topic_seeds.jsonl" in error for error in hard_errors)
    candidate_instances_valid = not any(error.startswith("candidate_event_instances:") for error in hard_errors)
    formal_events_valid = not any(error.startswith("events:") for error in hard_errors)
    return {
        "topic_seed_valid": topic_seed_valid,
        "candidate_instances_valid": candidate_instances_valid,
        "formal_events_valid": formal_events_valid,
        "formal_events_ready": formal_events_valid and bool(formal_events),
        "num_topic_seeds": len(topic_seeds),
        "num_candidate_instances": len(candidates),
        "num_formal_events": len(formal_events),
        "hard_errors": hard_errors,
        "warnings": warnings,
    }


def validate_candidate_for_promotion(candidate: dict[str, Any], label: str) -> list[str]:
    event = {
        "event_id": candidate.get("candidate_event_id"),
        "topic_id": candidate.get("topic_id"),
        "event_name": candidate.get("candidate_event_name"),
        "event_description": candidate.get("candidate_event_description"),
        "location": candidate.get("location"),
        "time_window": candidate.get("time_window"),
        "trigger": candidate.get("trigger"),
        "anchor_entities": candidate.get("anchor_entities"),
        "anchor_urls": candidate.get("anchor_urls"),
        "source_scope": candidate.get("source_scope"),
        "queries": candidate.get("discovery_queries"),
        "selection_status": "accepted",
        "instance_version": candidate.get("instance_version") or "v1",
    }
    return [error.replace("formal_event", label) for error in validate_formal_event_record(event, "formal_event")]


def validate_formal_event_record(event: dict[str, Any], label: str = "event") -> list[str]:
    errors: list[str] = []
    _require(
        event,
        [
            "event_id",
            "topic_id",
            "event_name",
            "event_description",
            "location",
            "time_window",
            "trigger",
            "anchor_entities",
            "anchor_urls",
            "source_scope",
            "queries",
            "selection_status",
            "instance_version",
        ],
        label,
        errors,
    )
    try:
        EventRecord.model_validate(event)
    except Exception as exc:
        errors.append(f"{label} schema error: {exc}")
    if _contains_placeholder(event):
        errors.append(f"{label} contains topic-level placeholder text")
    if not _has_factual_time_window(event.get("time_window")):
        errors.append(f"{label} missing factual time_window")
    if "social_media" in [str(item) for item in event.get("source_scope", []) if isinstance(event.get("source_scope"), list)]:
        errors.append(f"{label} source_scope uses social_media; use public_social")
    return errors


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


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return any(marker in value for marker in PLACEHOLDER_MARKERS)
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def _has_factual_time_window(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    start = str(value.get("start") or "").strip()
    end = str(value.get("end") or "").strip()
    return bool(start and end)
