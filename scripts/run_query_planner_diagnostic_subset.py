"""Select a diagnostic event subset and optionally run query-planner ablation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
from pathlib import Path
from typing import Any

from episoa.collector.query_planner import anchor_entity_terms
from episoa.data.loader import read_jsonl
from episoa.data.validator import validate_formal_event_record


ROOT = Path(__file__).resolve().parents[1]
ABLATION_SCRIPT_PATH = ROOT / "scripts" / "run_query_planner_ablation.py"
SPEC = importlib.util.spec_from_file_location("query_planner_ablation_script", ABLATION_SCRIPT_PATH)
ablation_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ablation_script)


DEFAULT_OUTPUT_DIR = Path("outputs/runs/query_planner_diagnostic_10")
STRATA_PLAN = [
    ("entity_complex", 3),
    ("official_response_heavy", 3),
    ("multi_source_discussion", 2),
    ("simple", 2),
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest) if args.manifest else output_dir / "diagnostic_event_subset_manifest.json"
    result = run_diagnostic_subset(
        config_path=Path(args.config),
        events_path=Path(args.events),
        output_dir=output_dir,
        manifest_path=manifest_path,
        num_events=args.num_events,
        seed=args.seed,
        dry_run=args.dry_run,
        manifest_only=args.manifest_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"completed", "manifest_written"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a reproducible 10-event diagnostic planner ablation.")
    parser.add_argument("--config", default="configs/collector.yaml")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--num-events", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic fixture search for the ablation run.")
    parser.add_argument("--manifest-only", action="store_true", help="Only write the subset manifest; do not run ablation.")
    return parser


def run_diagnostic_subset(
    *,
    config_path: Path,
    events_path: Path,
    output_dir: Path,
    manifest_path: Path,
    num_events: int,
    seed: int,
    dry_run: bool,
    manifest_only: bool = False,
) -> dict[str, Any]:
    events = _load_valid_events(events_path)
    selected = select_diagnostic_events(events, num_events=num_events, seed=seed)
    event_ids = [item["event_id"] for item in selected]
    manifest = {
        "selection_name": "query_planner_diagnostic_subset",
        "selection_version": 1,
        "seed": seed,
        "num_requested": num_events,
        "num_selected": len(selected),
        "selection_logic": {
            "entity_complex": "high anchor-entity count plus source/query/stakeholder breadth",
            "official_response_heavy": "official source present plus government/agency anchors or response-style stance hints",
            "multi_source_discussion": "broad source_scope with public_social or forum discussion sources",
            "simple": "lower entity/source/query complexity for contrast",
        },
        "event_ids": event_ids,
        "events": selected,
    }
    _write_json(manifest_path, manifest)
    (manifest_path.parent / "diagnostic_event_ids.txt").write_text("\n".join(event_ids) + "\n", encoding="utf-8")
    if manifest_only:
        return {
            "status": "manifest_written",
            "manifest_path": str(manifest_path),
            "event_ids": event_ids,
        }
    ablation_result = ablation_script.run_ablation(
        config_path=config_path,
        events_path=events_path,
        output_dir=output_dir,
        event_ids=set(event_ids),
        dry_run=dry_run,
    )
    ablation_result.update(
        {
            "manifest_path": str(manifest_path),
            "event_ids": event_ids,
        }
    )
    return ablation_result


def select_diagnostic_events(events: list[dict[str, Any]], *, num_events: int = 10, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    scored = [_event_scores(event, rng.random()) for event in events]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    remaining_slots = num_events
    plan = list(STRATA_PLAN)
    if num_events != 10:
        scale = num_events / 10
        plan = [(name, max(1, round(count * scale))) for name, count in STRATA_PLAN]
    for stratum, quota in plan:
        if remaining_slots <= 0:
            break
        for item in sorted(scored, key=lambda row: (-float(row["scores"][stratum]), float(row["tie_breaker"]), row["event_id"])):
            if len([row for row in selected if row["selection_stratum"] == stratum]) >= min(quota, remaining_slots):
                break
            if item["event_id"] in selected_ids:
                continue
            selected.append(_selected_manifest_row(item, stratum))
            selected_ids.add(str(item["event_id"]))
        remaining_slots = num_events - len(selected)
    if len(selected) < num_events:
        for item in sorted(scored, key=lambda row: (-float(row["scores"]["overall_complexity"]), float(row["tie_breaker"]), row["event_id"])):
            if item["event_id"] in selected_ids:
                continue
            selected.append(_selected_manifest_row(item, "backfill"))
            selected_ids.add(str(item["event_id"]))
            if len(selected) >= num_events:
                break
    return selected[:num_events]


def _event_scores(event: dict[str, Any], tie_breaker: float) -> dict[str, Any]:
    anchors = anchor_entity_terms(event)
    sources = list(event.get("source_scope") or [])
    queries = list(event.get("query_seeds") or [])
    stakeholders = list(event.get("stakeholder_hints") or [])
    stances = list(event.get("stance_hints") or [])
    anchor_keys = set(event.get("anchor_entities") or {})
    stance_text = " ".join(stances)
    official_signal = int("official" in sources) + int(bool(anchor_keys & {"government", "agency", "official"}))
    official_signal += int(any(term in stance_text for term in ("回应", "整改", "解释")))
    multi_source_signal = len(set(sources)) + int("public_social" in sources) + int("forum" in sources)
    complexity = len(anchors) + len(sources) + len(queries) + len(stakeholders)
    scores = {
        "entity_complex": len(anchors) * 3 + len(stakeholders) + len(queries) + len(sources),
        "official_response_heavy": official_signal * 4 + len([item for item in sources if item == "official"]),
        "multi_source_discussion": multi_source_signal * 3 + len(stances),
        "simple": -complexity,
        "overall_complexity": complexity,
    }
    return {
        "event_id": str(event.get("event_id")),
        "event_name": event.get("event_name"),
        "domain": event.get("domain"),
        "scores": scores,
        "features": {
            "num_anchor_entities": len(anchors),
            "num_source_types": len(set(sources)),
            "num_query_seeds": len(queries),
            "num_stakeholder_hints": len(stakeholders),
            "num_stance_hints": len(stances),
            "source_scope": sources,
        },
        "tie_breaker": tie_breaker,
    }


def _selected_manifest_row(item: dict[str, Any], stratum: str) -> dict[str, Any]:
    features = item["features"]
    return {
        "event_id": item["event_id"],
        "event_name": item["event_name"],
        "domain": item["domain"],
        "selection_stratum": stratum,
        "features": features,
        "selection_rationale": (
            f"Selected for {stratum}; anchors={features['num_anchor_entities']}, "
            f"sources={features['num_source_types']}, queries={features['num_query_seeds']}, "
            f"stakeholders={features['num_stakeholder_hints']}, stances={features['num_stance_hints']}."
        ),
    }


def _load_valid_events(events_path: Path) -> list[dict[str, Any]]:
    events = read_jsonl(events_path)
    errors = [
        error
        for index, event in enumerate(events, start=1)
        for error in validate_formal_event_record(event, f"events:{index}")
    ]
    if errors:
        raise SystemExit("formal event validation failed:\n" + "\n".join(errors))
    return events


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
