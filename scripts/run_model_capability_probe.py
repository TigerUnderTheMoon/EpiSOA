#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe LLM extraction capacity with oracle gold evidence on 10 events."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from episoa.attribution.schema_attributor import SchemaAttributor, select_oracle_prompt_evidence  # noqa: E402
from episoa.config import load_config  # noqa: E402
from episoa.evaluation.metrics import soft_tuple_f1  # noqa: E402
from episoa.llm.client import build_llm_client  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    raw_config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    probe_config = dict(raw_config.get("probe") or {})
    output_dir = ROOT / str(probe_config.get("output_dir") or args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    events = read_jsonl(ROOT / config.data["events_path"])
    evidence = read_jsonl(ROOT / config.data["evidence_path"])
    gold = read_jsonl(ROOT / config.data["gold_tuples_path"])
    selected_events = select_probe_events(events, gold, probe_config, args.event_ids)
    models = probe_models(config.model, probe_config, args.stronger_model)
    max_evidence = int(probe_config.get("max_evidence_per_event") or args.max_evidence)

    all_rows: list[dict[str, Any]] = []
    all_predictions: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    for model_name in models:
        model_config = dict(config.model)
        model_config["llm_model"] = model_name
        model_config["model_name"] = model_name
        try:
            client = build_llm_client(model_config)
            setup_error = ""
        except Exception as exc:
            client = None
            setup_error = str(exc)

        model_predictions: list[dict[str, Any]] = []
        for event, category in selected_events:
            event_id = str(event.get("event_id"))
            gold_rows = [row for row in gold if str(row.get("event_id")) == event_id]
            evidence_rows = [row for row in evidence if str(row.get("event_id")) == event_id]
            oracle_ids = oracle_evidence_ids(gold_rows)
            prompt_evidence = select_oracle_prompt_evidence(
                event=event,
                chain={},
                evidence_rows=evidence_rows,
                oracle_evidence_ids=oracle_ids,
                max_evidence=max_evidence,
                skip_chain_ranking=True,
            )
            raw_record: dict[str, Any] = {
                "event_id": event_id,
                "model_name": model_name,
                "probe_category": category,
                "oracle_gold_evidence_ids": oracle_ids,
                "selected_evidence_ids": [row.get("evidence_id") for row in prompt_evidence],
                "parse_success": False,
                "parse_error": setup_error,
                "raw_response": "",
            }
            event_predictions: list[dict[str, Any]] = []
            if client is None:
                error_category = "api_setup_error"
            else:
                attributor = SchemaAttributor(llm_client=client, model_name=model_name)
                try:
                    event_predictions, raw_record = attributor.attribute_event(
                        event=event,
                        chain={},
                        evidence_items=prompt_evidence,
                        stakeholder_candidates=[str(item) for item in event.get("stakeholder_hints", [])],
                        selection_metadata={
                            "probe_category": category,
                            "oracle_evidence": True,
                            "oracle_gold_evidence_ids": oracle_ids,
                        },
                        dry_run=args.dry_run,
                        hide_chain_in_prompt=True,
                        skip_chain_ranking=True,
                    )
                    raw_record["probe_category"] = category
                    error_category = categorize_event_error(gold_rows, event_predictions, raw_record)
                except Exception as exc:
                    raw_record["parse_error"] = str(exc)
                    error_category = "api_or_runtime_error"

            for row in event_predictions:
                row["probe_category"] = category
                row["model_name"] = model_name
                all_predictions.append(row)
                model_predictions.append(row)
            metric = soft_tuple_f1(gold_rows, event_predictions, threshold=0.5)
            all_rows.append({
                "scope": "event",
                "model_name": model_name,
                "event_id": event_id,
                "probe_category": category,
                "gold_tuple_count": len(gold_rows),
                "selected_evidence_count": len(prompt_evidence),
                "oracle_gold_evidence_count": len(oracle_ids),
                "oracle_gold_evidence_in_prompt_count": len(set(oracle_ids) & {str(row.get("evidence_id")) for row in prompt_evidence}),
                "Tuple-F1-soft": metric["f1"],
                "Precision": metric["precision"],
                "Recall": metric["recall"],
                "Num-Tuples": len(event_predictions),
                "parse_success": raw_record.get("parse_success"),
                "zero_pred_count": int(len(event_predictions) == 0),
                "sentiment_acc": metric["sentiment_accuracy"],
                "error_category": error_category,
            })
            all_raw.append(raw_record)

        aggregate = soft_tuple_f1(gold_for_selected(gold, selected_events), model_predictions, threshold=0.5)
        all_rows.append({
            "scope": "aggregate",
            "model_name": model_name,
            "event_id": "",
            "probe_category": "all",
            "gold_tuple_count": len(gold_for_selected(gold, selected_events)),
            "selected_evidence_count": "",
            "oracle_gold_evidence_count": "",
            "oracle_gold_evidence_in_prompt_count": "",
            "Tuple-F1-soft": aggregate["f1"],
            "Precision": aggregate["precision"],
            "Recall": aggregate["recall"],
            "Num-Tuples": len(model_predictions),
            "parse_success": "",
            "zero_pred_count": sum(1 for row in all_rows if row["scope"] == "event" and row["model_name"] == model_name and int(row["zero_pred_count"]) == 1),
            "sentiment_acc": aggregate["sentiment_accuracy"],
            "error_category": "",
        })

    write_csv(output_dir / "model_capability_probe_results.csv", all_rows)
    write_jsonl(output_dir / "model_capability_probe_predictions.jsonl", all_predictions)
    write_jsonl(output_dir / "model_capability_probe_raw_llm_responses.jsonl", all_raw)
    write_report(output_dir, all_rows, selected_events, models)
    print(json.dumps({
        "status": "completed",
        "output_dir": str(output_dir.relative_to(ROOT)),
        "models": models,
        "events": [event.get("event_id") for event, _ in selected_events],
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a 10-event oracle-evidence LLM capability probe.")
    parser.add_argument("--config", default="configs/ablation_oracle_evidence.yaml")
    parser.add_argument("--output-dir", default="outputs/model_probe")
    parser.add_argument("--max-evidence", type=int, default=20)
    parser.add_argument("--event-ids", default="", help="Optional comma-separated event IDs.")
    parser.add_argument("--stronger-model", default="", help="Optional model override for the stronger-model slot.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Accepted for symmetry; output files are backed up before overwrite.")
    return parser


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    backup_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    backup_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def backup_existing(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_{stamp}"))


def select_probe_events(
    events: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    probe_config: dict[str, Any],
    event_ids_arg: str,
) -> list[tuple[dict[str, Any], str]]:
    event_by_id = {str(row.get("event_id")): row for row in events}
    if event_ids_arg.strip():
        return [(event_by_id[event_id], "manual") for event_id in split_ids(event_ids_arg) if event_id in event_by_id][:10]
    gold_counts = defaultdict(int)
    for row in gold:
        gold_counts[str(row.get("event_id"))] += 1
    selected: list[tuple[str, str]] = []
    for event_id in probe_config.get("zero_prediction_events", [])[:4]:
        if event_id in event_by_id:
            selected.append((event_id, "p0_zero_prediction"))
    high_count = int(probe_config.get("high_gold_event_count") or 3)
    for event_id, _count in sorted(gold_counts.items(), key=lambda item: (-item[1], item[0])):
        if len([item for item in selected if item[1] == "high_gold_count"]) >= high_count:
            break
        if event_id not in {item[0] for item in selected} and event_id in event_by_id:
            selected.append((event_id, "high_gold_count"))
    normal_count = int(probe_config.get("normal_event_count") or 3)
    median_count = sorted(gold_counts.values())[len(gold_counts) // 2] if gold_counts else 3
    normal_candidates = sorted(
        [event_id for event_id in event_by_id if event_id not in {item[0] for item in selected}],
        key=lambda eid: (abs(gold_counts.get(eid, 0) - median_count), eid),
    )
    for event_id in normal_candidates[:normal_count]:
        selected.append((event_id, "normal"))
    return [(event_by_id[event_id], category) for event_id, category in selected[:10]]


def probe_models(model_config: dict[str, Any], probe_config: dict[str, Any], stronger_model_arg: str) -> list[str]:
    current = str(probe_config.get("current_model") or model_config.get("llm_model") or model_config.get("model_name") or "").strip()
    stronger = str(stronger_model_arg or probe_config.get("stronger_model") or "").strip()
    models = [model for model in [current, stronger] if model]
    return list(dict.fromkeys(models))


def oracle_evidence_ids(gold_rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in gold_rows:
        for evidence_id in get_evidence_ids(row):
            if evidence_id not in seen:
                seen.add(evidence_id)
                ordered.append(evidence_id)
                break
    for row in gold_rows:
        for evidence_id in get_evidence_ids(row):
            if evidence_id not in seen:
                seen.add(evidence_id)
                ordered.append(evidence_id)
    return ordered


def get_evidence_ids(row: dict[str, Any]) -> list[str]:
    value = row.get("evidence_ids")
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[;|,]", value) if item.strip()]
    return []


def gold_for_selected(gold: list[dict[str, Any]], selected_events: list[tuple[dict[str, Any], str]]) -> list[dict[str, Any]]:
    ids = {str(event.get("event_id")) for event, _ in selected_events}
    return [row for row in gold if str(row.get("event_id")) in ids]


def categorize_event_error(gold_rows: list[dict[str, Any]], predictions: list[dict[str, Any]], raw_record: dict[str, Any]) -> str:
    if raw_record.get("parse_success") is False:
        return "parse_failure"
    if not predictions:
        return "zero_prediction"
    metric = soft_tuple_f1(gold_rows, predictions, threshold=0.5)
    if metric["recall"] < 0.25:
        return "low_recall"
    if metric["precision"] < 0.5:
        return "low_precision"
    if metric["sentiment_accuracy"] < 0.6:
        return "sentiment_mismatch"
    return "ok"


def write_report(output_dir: Path, rows: list[dict[str, Any]], selected_events: list[tuple[dict[str, Any], str]], models: list[str]) -> None:
    backup_existing(output_dir / "model_capability_probe_report.md")
    aggregate_rows = [row for row in rows if row.get("scope") == "aggregate"]
    lines = [
        "# Model Capability Probe Report",
        "",
        "## Design",
        "- 10 events are selected from P0 zero-prediction, high-gold-count, and normal events.",
        "- Each event uses oracle gold evidence IDs only; gold tuple text is never passed to the model.",
        "- Graph and event-chain ranking are disabled; the prompt uses evidence-only extraction.",
        "",
        "## Events",
    ]
    for event, category in selected_events:
        lines.append(f"- {event.get('event_id')}: {category} / {event.get('event_name', '')}")
    lines.extend(["", "## Aggregate Results"])
    for row in aggregate_rows:
        lines.append(
            f"- {row['model_name']}: F1={row['Tuple-F1-soft']}, P={row['Precision']}, R={row['Recall']}, tuples={row['Num-Tuples']}, zero_events={row['zero_pred_count']}, sentiment_acc={row['sentiment_acc']}"
        )
    lines.extend([
        "",
        "## Required Answers",
        "- If current-model F1 remains low under oracle evidence, the likely bottleneck shifts to prompt/extraction/gold consistency/evaluation.",
        "- If a stronger model is configured and improves materially, current model capacity is a contributor.",
        "- If the stronger model also remains low, prioritize gold cleanup, prompt redesign, and metric audit before scaling API spend.",
    ])
    (output_dir / "model_capability_probe_report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def split_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
