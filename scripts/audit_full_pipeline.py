#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate full-pipeline audit reports for the PubEvent-SOA Lite run."""

from __future__ import annotations

import csv
import json
import math
import random
import re
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from episoa.attribution.schema_attributor import (  # noqa: E402
    select_oracle_prompt_evidence,
    select_prompt_evidence,
    stakeholder_candidates_by_event,
)
from episoa.evaluation.metrics import soft_tuple_f1  # noqa: E402
from episoa.graph.evidence_graph import build_stakeholder_event_evidence_graph  # noqa: E402
from episoa.retrieval.event_chain_retriever import EventChainRetriever  # noqa: E402


AUDIT_DIR = ROOT / "outputs" / "audit_full_pipeline"
EVENTS_PATH = ROOT / "data" / "pubevent_soa_lite" / "events.jsonl"
EVIDENCE_PATH = ROOT / "data" / "pubevent_soa_lite" / "evidence_v3_repaired_plus_low37.jsonl"
PRIMARY_GOLD_TUPLES = ROOT / "data" / "pubevent_soa_lite" / "annotation_full_v3_repaired_plus_low37" / "llm_gold_tuples.jsonl"
PRIMARY_GOLD_CHAINS = ROOT / "data" / "pubevent_soa_lite" / "annotation_full_v3_repaired_plus_low37" / "llm_gold_event_chains.jsonl"
HUMAN_GOLD_TUPLES = ROOT / "data" / "pubevent_soa_lite" / "annotation_full_v3_repaired_plus_low37" / "human_reviewed_gold" / "gold_tuples.jsonl"
HUMAN_GOLD_CHAINS = ROOT / "data" / "pubevent_soa_lite" / "annotation_full_v3_repaired_plus_low37" / "human_reviewed_gold" / "gold_event_chains.jsonl"
REVIEW_SHEET = ROOT / "data" / "pubevent_soa_lite" / "annotation_full_v3_repaired_plus_low37" / "review_sheets" / "gold_tuple_review_sheet_reviewed.csv"
P0_FULL_DIR = ROOT / "outputs" / "runs_p0_parse_repair" / "ablation_full"
OLD_FULL_DIR = ROOT / "outputs" / "runs" / "ablation_full"
BENCHMARK_DIR = ROOT / "data" / "benchmark" / "pubevent_soa_lite_v3_repaired_plus_low37_gold"
ORACLE_DIR = ROOT / "outputs" / "runs_oracle_evidence"
MODEL_PROBE_DIR = ROOT / "outputs" / "model_probe"


def main() -> int:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    events = read_jsonl(EVENTS_PATH)
    evidence = read_jsonl(EVIDENCE_PATH)
    gold = read_jsonl(PRIMARY_GOLD_TUPLES)
    gold_chains = read_jsonl(PRIMARY_GOLD_CHAINS)
    predictions = read_jsonl(P0_FULL_DIR / "predictions.jsonl")
    raw_records = read_jsonl(P0_FULL_DIR / "raw_llm_responses.jsonl")
    chains = EventChainRetriever(top_k_per_stage=5).retrieve_all(events, evidence)

    pipeline_summary = write_pipeline_file_map()
    gold_summary = write_gold_quality_audit(events, evidence, gold, gold_chains)
    evidence_summary = write_evidence_coverage_audit(events, evidence, gold, predictions, raw_records, chains)
    graph_summary = write_graph_quality_audit(events, evidence, gold, gold_chains, chains)
    metric_summary = write_evaluation_metric_audit(gold, predictions)
    fairness_summary = write_experiment_fairness_audit()
    scale_summary = write_dataset_scale_audit(events, evidence, gold, gold_chains)
    write_oracle_evidence_report(gold)
    write_final_report(
        pipeline_summary=pipeline_summary,
        gold_summary=gold_summary,
        evidence_summary=evidence_summary,
        graph_summary=graph_summary,
        metric_summary=metric_summary,
        fairness_summary=fairness_summary,
        scale_summary=scale_summary,
    )
    print(json.dumps({
        "status": "completed",
        "audit_dir": rel(AUDIT_DIR),
        "reports": sorted(str(path.relative_to(ROOT)) for path in AUDIT_DIR.glob("*")),
    }, ensure_ascii=False, indent=2))
    return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{lineno} is not a JSON object")
            rows.append(value)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_text(path: Path, text: str) -> None:
    backup_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, obj: Any) -> None:
    backup_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    backup_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_cell(row.get(field, "")) for field in fieldnames})


def backup_existing(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{stamp}")
    shutil.copy2(path, backup)


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def file_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": rel(path),
        "exists": path.exists(),
        "line_count": 0,
        "record_count": 0,
        "key_fields": [],
    }
    if not path.exists() or path.is_dir():
        return info
    text = path.read_text(encoding="utf-8", errors="replace")
    info["line_count"] = len(text.splitlines())
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = read_jsonl(path)
        info["record_count"] = len(rows)
        keys = Counter(key for row in rows for key in row)
        info["key_fields"] = [key for key, _ in keys.most_common(12)]
    elif suffix == ".csv":
        rows = read_csv(path)
        info["record_count"] = len(rows)
        info["key_fields"] = list(rows[0].keys())[:12] if rows else []
    elif suffix == ".json":
        obj = read_json(path)
        info["record_count"] = 1 if obj else 0
        info["key_fields"] = list(obj.keys())[:12]
    else:
        info["record_count"] = info["line_count"]
    return info


def describe_values(values: list[int | float]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "median": 0, "mean": 0, "max": 0}
    return {
        "min": min(values),
        "median": round(statistics.median(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "max": max(values),
    }


def group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    return grouped


def evidence_ids(row: dict[str, Any]) -> list[str]:
    value = row.get("evidence_ids")
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[;|,]", value) if item.strip()]
    value = row.get("evidence_id")
    return [str(value)] if value else []


def write_pipeline_file_map() -> dict[str, Any]:
    stage_specs = [
        ("event registry", ["scripts/validate_events.py", "scripts/upgrade_events_schema.py"], ["configs/default.yaml"], [], ["data/pubevent_soa_lite/events.jsonl"], "no", "no", "no", "no", "low", "yes"),
        ("evidence collection", ["scripts/collect_evidence.py"], ["configs/collector.yaml", "configs/collector_budget_50.yaml", "configs/source_detection.yaml"], ["data/pubevent_soa_lite/events.jsonl"], ["data/pubevent_soa_lite/raw/raw_posts.jsonl", "outputs/runs/collector_*"], "yes unless versioned output dir is used", "yes", "yes", "no", "low", "yes"),
        ("evidence normalization / filtering", ["scripts/normalize_evidence.py", "scripts/filter_evidence_quality.py", "scripts/merge_evidence.py"], ["configs/source_detection.yaml"], ["data/pubevent_soa_lite/raw/raw_posts.jsonl", "data/pubevent_soa_lite/interim/evidence_candidates*.jsonl"], ["data/pubevent_soa_lite/evidence_filtered.jsonl", "data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl"], "yes unless backup flag/script copy is used", "no", "no", "no", "low", "yes"),
        ("annotation sheet construction", ["scripts/make_annotation_sheet.py", "scripts/build_gold_review_sheets.py"], ["configs/paper.yaml"], ["events.jsonl", "evidence_v3_repaired_plus_low37.jsonl", "candidate_soa_tuples.jsonl"], ["annotation_sheet.csv", "review_sheets/*.csv"], "yes", "no", "no", "may read candidate predictions", "medium if predictions are evaluated as gold", "not final paper metric"),
        ("LLM preannotation", ["scripts/run_llm_gold_preannotation.py"], ["configs/paper.yaml", "prompts/gold_*_preannotation.md"], ["events.jsonl", "evidence_v3_repaired_plus_low37.jsonl"], ["llm_gold_tuples.jsonl", "llm_gold_event_chains.jsonl", "llm_preannotation_audit.jsonl"], "yes when merge/overwrite enabled", "yes", "no", "no", "high if treated as final gold", "no unless explicitly silver"),
        ("human review / gold export", ["scripts/build_gold_review_sheets.py", "scripts/convert_review_sheets_to_gold.py"], ["docs/gold_annotation_workflow.md"], ["review_sheets/*_reviewed.csv", "evidence_v3_repaired_plus_low37.jsonl"], ["human_reviewed_gold/gold_tuples.jsonl", "data/releases/*/gold_tuples.jsonl"], "yes with backup in release scripts", "no", "no", "reads candidate tuples", "medium; reviewer must be independent", "yes only with real human review"),
        ("gold validation", ["scripts/validate_gold_dataset.py", "scripts/summarize_gold_dataset.py"], ["configs/paper.yaml"], ["gold_tuples.jsonl", "gold_event_chains.jsonl", "evidence_v3_repaired_plus_low37.jsonl"], ["gold_validation_report.json", "dataset_statistics.*"], "yes", "no", "no", "yes", "low", "yes"),
        ("benchmark task construction", ["scripts/build_benchmark_tasks.py"], [], ["release/events.jsonl", "release/evidence.jsonl", "release/gold_tuples.jsonl", "release/gold_event_chains.jsonl"], ["data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold/*.jsonl"], "yes, script supports backup", "no", "no", "yes", "high if benchmark includes output labels in prompts", "yes for benchmark release"),
        ("graph construction", ["scripts/build_evidence_graph.py", "src/episoa/graph/evidence_graph.py"], [], ["events.jsonl", "evidence_v3_repaired_plus_low37.jsonl"], ["outputs/runs/*/evidence_graph/*.jsonl"], "yes per run dir", "no", "no", "no", "low", "yes"),
        ("event-chain retrieval", ["src/episoa/retrieval/event_chain_retriever.py", "scripts/retrieve_event_chains.py"], ["configs/paper.yaml"], ["events.jsonl", "evidence_v3_repaired_plus_low37.jsonl"], ["in-memory chains", "retrieval_results.csv"], "yes per run dir", "no", "no", "no", "low", "yes"),
        ("schema attribution", ["src/episoa/attribution/schema_attributor.py"], ["configs/paper.yaml", "prompts/benchmark_tuple_*.md"], ["events.jsonl", "evidence_v3_repaired_plus_low37.jsonl", "chains", "graph_nodes"], ["candidate_soa_tuples.jsonl", "raw_llm_responses.jsonl"], "yes per run dir", "yes", "no", "no", "medium; oracle mode intentionally reads gold evidence ids", "yes"),
        ("verifier", ["src/episoa/verifier/faithfulness_verifier.py"], ["configs/paper.yaml"], ["candidate_soa_tuples.jsonl", "evidence_v3_repaired_plus_low37.jsonl"], ["verified_soa_tuples.jsonl", "predictions.jsonl"], "yes per run dir", "yes", "no", "no", "low", "yes"),
        ("main experiment", ["scripts/run_paper_experiment.py", "src/episoa/pipeline.py"], ["configs/paper.yaml"], ["events.jsonl", "evidence_v3_repaired_plus_low37.jsonl", "llm_gold_tuples.jsonl"], ["outputs/runs/pubevent-soa-lite-paper/*"], "yes", "yes", "no", "yes for evaluation only", "medium if gold file is pseudo-gold", "yes after gold fix"),
        ("ablation experiment", ["scripts/run_ablation.py", "src/episoa/pipeline.py"], ["configs/ablation.yaml", "configs/ablation_p0_parse_repair.yaml"], ["same as main"], ["outputs/runs/ablation_*", "outputs/runs_p0_parse_repair/ablation_full"], "yes with --force", "yes", "no", "yes for evaluation only", "medium if settings not rerun equally", "yes after P0 rerun"),
        ("evaluation", ["src/episoa/evaluation/*.py"], [], ["predictions.jsonl", "gold_tuples.jsonl"], ["metrics.json", "event_level_metrics.csv", "ablation_results.csv"], "yes per run dir", "no", "no", "yes", "medium; metric can under/over-estimate", "yes"),
        ("audit/report generation", ["scripts/audit_full_pipeline.py", "scripts/export_paper_tables.py"], [], ["all above outputs"], ["outputs/audit_full_pipeline/*", "outputs/paper_tables/*"], "yes; audit script backs up existing report files", "no", "no", "yes", "low if labelled diagnostic", "supporting material"),
    ]
    rows = []
    for spec in stage_specs:
        stage, scripts, configs, inputs, outputs, overwrites, api, search, reads_gold, leakage, reproduce = spec
        files = [ROOT / item for item in scripts + configs + inputs + outputs if "*" not in item and not item.startswith("same") and not item.startswith("in-memory")]
        infos = [file_info(path) for path in files]
        rows.append({
            "stage": stage,
            "entry_scripts": scripts,
            "config_files": configs,
            "input_files": inputs,
            "output_files": outputs,
            "overwrites_old_files": overwrites,
            "depends_api": api,
            "depends_search": search,
            "reads_gold": reads_gold,
            "leakage_risk": leakage,
            "should_enter_reproduction": reproduce,
            "file_info": infos,
        })
    lines = ["# Pipeline File Map and Input/Output Audit", ""]
    lines.append("| Stage | Entry Script | Config | Inputs | Outputs | Overwrite | API | Search | Reads Gold | Leakage Risk | Reproduce |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        lines.append("| {stage} | {entry} | {config} | {inputs} | {outputs} | {ow} | {api} | {search} | {gold} | {leak} | {rep} |".format(
            stage=row["stage"],
            entry="<br>".join(row["entry_scripts"]),
            config="<br>".join(row["config_files"]),
            inputs="<br>".join(row["input_files"]),
            outputs="<br>".join(row["output_files"]),
            ow=row["overwrites_old_files"],
            api=row["depends_api"],
            search=row["depends_search"],
            gold=row["reads_gold"],
            leak=row["leakage_risk"],
            rep=row["should_enter_reproduction"],
        ))
    lines.append("")
    lines.append("## File Inventory")
    for row in rows:
        lines.append(f"### {row['stage']}")
        for info in row["file_info"]:
            lines.append(
                f"- `{info['path']}`: exists={info['exists']}, lines={info['line_count']}, records={info['record_count']}, keys={', '.join(info['key_fields'])}"
            )
    write_text(AUDIT_DIR / "pipeline_file_map.md", "\n".join(lines))
    return {"stages": rows}


def write_gold_quality_audit(events: list[dict[str, Any]], evidence: list[dict[str, Any]], gold: list[dict[str, Any]], chains: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence}
    gold_by_event = group_by(gold, "event_id")
    human_gold = read_jsonl(HUMAN_GOLD_TUPLES)
    review_rows = read_csv(REVIEW_SHEET)
    provenance_fields = ["reviewed_by", "human_verified", "review_status", "annotator_id", "revision_note", "confidence", "source", "annotation_provenance"]
    primary_field_counts = Counter(key for row in gold for key in row)
    human_provenance = Counter(
        str((row.get("annotation_provenance") or {}).get("reviewer_id") or (row.get("annotation_provenance") or {}).get("annotator_id") or "")
        for row in human_gold
    )
    review_decisions = Counter(str(row.get("human_decision", "")) for row in review_rows)
    review_statuses = Counter(str(row.get("review_status", "")) for row in review_rows)
    annotators = Counter(str(row.get("annotator_id") or row.get("reviewer_id") or "") for row in review_rows)
    duplicate_flags = duplicate_tuple_ids(gold)

    by_event_rows = []
    for event_id in sorted(set(row.get("event_id") for row in gold)):
        rows = gold_by_event[event_id]
        event_eids = sorted({eid for row in rows for eid in evidence_ids(row)})
        missing = [eid for eid in event_eids if eid not in evidence_by_id]
        source_types = Counter(str(evidence_by_id.get(eid, {}).get("source_type") or evidence_by_id.get(eid, {}).get("source") or "missing") for eid in event_eids)
        domains = Counter(str(evidence_by_id.get(eid, {}).get("domain") or evidence_by_id.get(eid, {}).get("platform") or "missing") for eid in event_eids)
        issues = Counter(issue for row in rows for issue in suspected_issues(row, rows, evidence_by_id, duplicate_flags))
        by_event_rows.append({
            "event_id": event_id,
            "gold_tuple_count": len(rows),
            "unique_stakeholder_count": len({row.get("stakeholder", "") for row in rows}),
            "unique_sentiment_count": len({row.get("sentiment", "") for row in rows}),
            "unique_gold_evidence_count": len(event_eids),
            "tuple_without_evidence_count": sum(1 for row in rows if not evidence_ids(row)),
            "missing_evidence_ref_count": len(missing),
            "source_type_distribution": dict(source_types),
            "domain_distribution": dict(domains.most_common(8)),
            "avg_evidence_ids_per_tuple": round(sum(len(evidence_ids(row)) for row in rows) / len(rows), 4) if rows else 0,
            "issue_distribution": dict(issues),
        })

    sample_rows = build_gold_sample_rows(gold, evidence_by_id, duplicate_flags)
    write_csv(
        AUDIT_DIR / "gold_quality_by_event.csv",
        by_event_rows,
        ["event_id", "gold_tuple_count", "unique_stakeholder_count", "unique_sentiment_count", "unique_gold_evidence_count", "tuple_without_evidence_count", "missing_evidence_ref_count", "source_type_distribution", "domain_distribution", "avg_evidence_ids_per_tuple", "issue_distribution"],
    )
    write_csv(
        AUDIT_DIR / "gold_tuple_sample_for_human_review.csv",
        sample_rows,
        ["event_id", "candidate_id", "stakeholder", "opinion", "sentiment", "rationale", "evidence_ids", "evidence_title", "evidence_text_excerpt", "support_label", "suspected_issue"],
    )

    tuple_counts = [len(rows) for rows in gold_by_event.values()]
    evidence_id_counts = [len(evidence_ids(row)) for row in gold]
    support_dist = Counter(str(row.get("support_label", "")) for row in gold)
    sentiment_dist = Counter(str(row.get("sentiment", "")) for row in gold)
    stakeholder_dist = Counter(str(row.get("stakeholder", "")) for row in gold)
    all_gold_eids = [eid for row in gold for eid in evidence_ids(row)]
    gold_evidence_source = Counter(str(evidence_by_id.get(eid, {}).get("source_type") or evidence_by_id.get(eid, {}).get("source") or "missing") for eid in all_gold_eids)
    gold_evidence_domain = Counter(str(evidence_by_id.get(eid, {}).get("domain") or evidence_by_id.get(eid, {}).get("platform") or "missing") for eid in all_gold_eids)
    summary = {
        "classification": "silver/pseudo-gold, not strictly human-verified gold",
        "primary_gold_file": rel(PRIMARY_GOLD_TUPLES),
        "primary_gold_field_counts": dict(primary_field_counts),
        "primary_gold_has_human_fields": {field: field in primary_field_counts for field in provenance_fields},
        "human_reviewed_export_exists": bool(human_gold),
        "human_reviewed_export_reviewer_distribution": dict(human_provenance),
        "review_sheet_human_decision_distribution": dict(review_decisions),
        "review_sheet_review_status_distribution": dict(review_statuses),
        "review_sheet_annotator_distribution": dict(annotators),
        "events_count": len({row.get("event_id") for row in gold}),
        "gold_tuples_total": len(gold),
        "gold_event_chains_total": len(chains),
        "tuple_count_per_event": describe_values(tuple_counts),
        "events_with_less_than_2_tuples": sorted(event_id for event_id, rows in gold_by_event.items() if len(rows) < 2),
        "events_with_more_than_6_tuples": sorted(event_id for event_id, rows in gold_by_event.items() if len(rows) > 6),
        "support_label_distribution": dict(support_dist),
        "sentiment_distribution": dict(sentiment_dist),
        "stakeholder_top20": dict(stakeholder_dist.most_common(20)),
        "evidence_ids_per_tuple": describe_values(evidence_id_counts),
        "tuples_with_at_least_one_evidence_id": sum(1 for row in gold if evidence_ids(row)),
        "missing_evidence_ref_count": sum(1 for eid in all_gold_eids if eid not in evidence_by_id),
        "gold_evidence_source_type_distribution": dict(gold_evidence_source),
        "gold_evidence_domain_top20": dict(gold_evidence_domain.most_common(20)),
        "recommendation": {
            "can_call_gold": False,
            "must_human_verify": True,
            "188_tuples_enough_for_top_journal": False,
            "suggested_minimum": "100 events and 300-500 human-adjudicated tuples; stronger target is 150-200 events with 600+ tuples.",
            "recommended_name": "silver benchmark or weakly supervised benchmark until double human review is complete",
        },
    }
    write_json(AUDIT_DIR / "gold_quality_audit.json", summary)

    lines = [
        "# Gold Quality Audit",
        "",
        "## Verdict",
        "- Current experiment gold file should be labelled **silver/pseudo-gold, not strictly human-verified gold**.",
        f"- The configured file `{rel(PRIMARY_GOLD_TUPLES)}` has fields `{', '.join(summary['primary_gold_field_counts'])}` and no explicit human verification fields.",
        f"- The reviewed export exists, but reviewer/annotator distribution is `{dict(annotators)}` and all accepted rows are from `auto_reviewer`; this is not evidence of independent human review.",
        "",
        "## Counts",
        f"- Events with gold tuples: {summary['events_count']}",
        f"- Gold tuples: {summary['gold_tuples_total']}",
        f"- Gold chains: {summary['gold_event_chains_total']}",
        f"- Tuple count per event: {summary['tuple_count_per_event']}",
        f"- Events <2 tuples: {summary['events_with_less_than_2_tuples']}",
        f"- Events >6 tuples: {summary['events_with_more_than_6_tuples']}",
        "",
        "## Distributions",
        f"- support_label: {dict(support_dist)}",
        f"- sentiment: {dict(sentiment_dist)}",
        f"- gold evidence source_type: {dict(gold_evidence_source)}",
        "",
        "## Required Answers",
        "- Can it be called gold? No. It is LLM preannotation with an auto-reviewed export, so it should be called silver/pseudo-gold.",
        "- Must human verification be done? Yes. At least one real human pass is mandatory; for paper-grade benchmark claims, use two annotators plus adjudication.",
        "- Are 188 tuples enough? Not for a strong benchmark claim. It may support a pilot/diagnostic study, but not a convincing一区 benchmark.",
        "- Suggested expansion: minimum 100 events and 300-500 human-adjudicated tuples; better 150-200 events and 600+ tuples.",
        "- Naming: use silver benchmark / weakly supervised benchmark until real human verification is complete.",
    ]
    write_text(AUDIT_DIR / "gold_quality_audit.md", "\n".join(lines))
    return summary


def duplicate_tuple_ids(gold: list[dict[str, Any]]) -> set[int]:
    duplicates: set[int] = set()
    by_event = group_by(gold, "event_id")
    indexed = {id(row): idx for idx, row in enumerate(gold)}
    for rows in by_event.values():
        for i, left in enumerate(rows):
            for right in rows[i + 1:]:
                same_stake = char_jaccard(str(left.get("stakeholder", "")), str(right.get("stakeholder", ""))) >= 0.85
                same_opinion = char_jaccard(str(left.get("opinion", "")), str(right.get("opinion", ""))) >= 0.85
                if same_stake and same_opinion:
                    duplicates.add(indexed[id(left)])
                    duplicates.add(indexed[id(right)])
    return duplicates


def suspected_issues(row: dict[str, Any], event_rows: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]], duplicate_flags: set[int]) -> list[str]:
    issues: list[str] = []
    stakeholder = str(row.get("stakeholder", "")).strip()
    opinion = str(row.get("opinion", "")).strip()
    rationale = str(row.get("rationale", "")).strip()
    ids = evidence_ids(row)
    text = " ".join(str(evidence_by_id.get(eid, {}).get("title", "")) + " " + str(evidence_by_id.get(eid, {}).get("text", "")) for eid in ids)
    if len(opinion) < 8 or opinion in {"支持", "反对", "质疑", "回应", "满意", "不满"}:
        issues.append("vague_opinion")
    if stakeholder in {"公众", "群众", "民众", "网友", "媒体", "政府部门", "居民/公众", "专家/律师"} or len(stakeholder) <= 2:
        issues.append("stakeholder_too_generic")
    if not ids or any(eid not in evidence_by_id for eid in ids):
        issues.append("evidence_missing")
    if ids and text and weak_support(row, text):
        issues.append("evidence_weak_support")
    if str(row.get("sentiment")) == "mixed" or (str(row.get("sentiment")) == "positive" and any(term in stakeholder for term in ["政府", "部门", "局", "委"])):
        issues.append("sentiment_questionable")
    if any(row is other for other in event_rows):
        pass
    row_index = None
    for idx, candidate in enumerate(read_jsonl(PRIMARY_GOLD_TUPLES)):
        if candidate is row:
            row_index = idx
            break
    if row_index is not None and row_index in duplicate_flags:
        issues.append("duplicate_or_near_duplicate")
    elif any(other is not row and char_jaccard(stakeholder + opinion, str(other.get("stakeholder", "")) + str(other.get("opinion", ""))) >= 0.9 for other in event_rows):
        issues.append("duplicate_or_near_duplicate")
    if len(opinion) > 50 or len(rationale) > 100 or opinion.count("，") + opinion.count("；") >= 2 or any(term in opinion for term in ["同时", "以及", "并且"]):
        issues.append("too_long_or_not_atomic")
    return sorted(set(issues)) or ["no_issue_detected"]


def weak_support(row: dict[str, Any], evidence_text: str) -> bool:
    stakeholder = str(row.get("stakeholder", ""))
    opinion = str(row.get("opinion", ""))
    stake_hit = bool(stakeholder and stakeholder in evidence_text)
    grams = chinese_ngrams(opinion, n=2)
    opinion_hits = sum(1 for gram in grams if gram in evidence_text)
    if not grams:
        return True
    return (not stake_hit) and (opinion_hits / max(1, len(grams)) < 0.10)


def build_gold_sample_rows(gold: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]], duplicate_flags: set[int]) -> list[dict[str, Any]]:
    rng = random.Random(42)
    rows = list(gold)
    rng.shuffle(rows)
    rows = sorted(rows[:50], key=lambda row: (str(row.get("event_id", "")), str(row.get("candidate_id", ""))))
    by_event = group_by(gold, "event_id")
    sample = []
    for row in rows:
        ids = evidence_ids(row)
        ev = evidence_by_id.get(ids[0], {}) if ids else {}
        issue_list = suspected_issues(row, by_event.get(str(row.get("event_id", "")), []), evidence_by_id, duplicate_flags)
        sample.append({
            "event_id": row.get("event_id", ""),
            "candidate_id": row.get("candidate_id") or row.get("gold_tuple_id", ""),
            "stakeholder": row.get("stakeholder", ""),
            "opinion": row.get("opinion", ""),
            "sentiment": row.get("sentiment", ""),
            "rationale": row.get("rationale", ""),
            "evidence_ids": ids,
            "evidence_title": ev.get("title", ""),
            "evidence_text_excerpt": excerpt(ev.get("text", ""), 360),
            "support_label": row.get("support_label", ""),
            "suspected_issue": issue_list,
        })
    return sample


def write_evidence_coverage_audit(
    events: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    chains: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_by_event = group_by(gold, "event_id")
    pred_by_event = group_by(predictions, "event_id")
    raw_by_event = {str(row.get("event_id")): row for row in raw_records}
    chain_by_event = {str(row.get("event_id")): row for row in chains}
    event_rows = []
    overlap_rows = []
    for event in events:
        event_id = str(event.get("event_id"))
        gold_rows = gold_by_event.get(event_id, [])
        pred_rows = pred_by_event.get(event_id, [])
        gold_eids = sorted({eid for row in gold_rows for eid in evidence_ids(row)})
        selected = list(raw_by_event.get(event_id, {}).get("request_summary", {}).get("selected_evidence_ids", []) or [])
        selected_set = set(selected)
        chain_eids = chain_evidence_ids(chain_by_event.get(event_id, {}))
        chain_set = set(chain_eids)
        matched = soft_tuple_f1(gold_rows, pred_rows, threshold=0.5)
        parse_success = raw_by_event.get(event_id, {}).get("parse_success")
        zero_prediction = len(pred_rows) == 0
        gold_in_prompt = sorted(set(gold_eids) & selected_set)
        gold_in_chain = sorted(set(gold_eids) & chain_set)
        prompt_non_gold = sorted(selected_set - set(gold_eids))
        row = {
            "event_id": event_id,
            "gold_tuple_count": len(gold_rows),
            "gold_evidence_id_count": len(gold_eids),
            "selected_evidence_id_count": len(selected_set),
            "gold_evidence_in_prompt_count": len(gold_in_prompt),
            "gold_evidence_in_prompt_ratio": ratio(len(gold_in_prompt), len(gold_eids)),
            "gold_evidence_in_chain_count": len(gold_in_chain),
            "gold_evidence_in_chain_ratio": ratio(len(gold_in_chain), len(gold_eids)),
            "predicted_tuple_count": len(pred_rows),
            "matched_tuple_count": int(matched.get("true_positives", 0)),
            "zero_prediction": zero_prediction,
            "parse_success": parse_success,
            "chain_confidence": chain_by_event.get(event_id, {}).get("chain_confidence", 0),
            "num_chain_stages_covered": len([stage for stage in chain_by_event.get(event_id, {}).get("stages", []) if stage.get("evidence")]),
            "gold_evidence_not_in_prompt": sorted(set(gold_eids) - selected_set),
            "gold_evidence_not_in_chain": sorted(set(gold_eids) - chain_set),
            "selected_non_gold_evidence_count": len(prompt_non_gold),
            "zero_prediction_reason": zero_prediction_reason(gold_eids, selected_set, chain_set, chain_by_event.get(event_id, {}), parse_success),
        }
        event_rows.append(row)
        overlap_rows.append({
            "event_id": event_id,
            "gold_evidence_ids": gold_eids,
            "selected_evidence_ids": selected,
            "chain_evidence_ids": chain_eids,
            "gold_evidence_in_prompt": gold_in_prompt,
            "gold_evidence_in_chain": gold_in_chain,
            "selected_non_gold_evidence_ids": prompt_non_gold,
        })
    write_csv(AUDIT_DIR / "evidence_coverage_by_event.csv", event_rows, list(event_rows[0].keys()))
    write_csv(AUDIT_DIR / "prompt_gold_evidence_overlap.csv", overlap_rows, list(overlap_rows[0].keys()))

    ratios_prompt = [row["gold_evidence_in_prompt_ratio"] for row in event_rows if row["gold_evidence_id_count"]]
    ratios_chain = [row["gold_evidence_in_chain_ratio"] for row in event_rows if row["gold_evidence_id_count"]]
    tuple_prompt_covered = sum(1 for row in gold if set(evidence_ids(row)) & set(raw_by_event.get(str(row.get("event_id")), {}).get("request_summary", {}).get("selected_evidence_ids", []) or []))
    summary = {
        "avg_gold_evidence_in_prompt_ratio": round(sum(ratios_prompt) / len(ratios_prompt), 4) if ratios_prompt else 0,
        "median_gold_evidence_in_prompt_ratio": round(statistics.median(ratios_prompt), 4) if ratios_prompt else 0,
        "avg_gold_evidence_in_chain_ratio": round(sum(ratios_chain) / len(ratios_chain), 4) if ratios_chain else 0,
        "median_gold_evidence_in_chain_ratio": round(statistics.median(ratios_chain), 4) if ratios_chain else 0,
        "events_with_no_gold_evidence_in_prompt": [row["event_id"] for row in event_rows if row["gold_evidence_id_count"] and row["gold_evidence_in_prompt_count"] == 0],
        "events_with_no_gold_evidence_in_chain": [row["event_id"] for row in event_rows if row["gold_evidence_id_count"] and row["gold_evidence_in_chain_count"] == 0],
        "zero_prediction_events": [row for row in event_rows if row["zero_prediction"]],
        "coverage_constrained_tuple_recall_upper_bound": round(tuple_prompt_covered / len(gold), 4) if gold else 0,
    }
    oracle_metrics = read_oracle_metrics()
    lines = [
        "# Evidence Coverage Audit",
        "",
        "## Summary",
        f"- Average gold evidence in prompt ratio: {summary['avg_gold_evidence_in_prompt_ratio']}",
        f"- Median gold evidence in prompt ratio: {summary['median_gold_evidence_in_prompt_ratio']}",
        f"- Average gold evidence in event-chain ratio: {summary['avg_gold_evidence_in_chain_ratio']}",
        f"- Coverage-constrained tuple recall upper bound if extraction were perfect on any prompted gold evidence: {summary['coverage_constrained_tuple_recall_upper_bound']}",
        f"- Events with zero gold evidence in prompt: {summary['events_with_no_gold_evidence_in_prompt']}",
        f"- Events with zero gold evidence in chain: {summary['events_with_no_gold_evidence_in_chain']}",
        "",
        "## P0 Zero-Prediction Events",
    ]
    for row in [item for item in event_rows if item["event_id"] in {"E001", "E002", "E010", "E032", "E033", "E037", "E038", "E047"}]:
        lines.append(
            f"- {row['event_id']}: prompt_gold={row['gold_evidence_in_prompt_count']}/{row['gold_evidence_id_count']}, chain_gold={row['gold_evidence_in_chain_count']}/{row['gold_evidence_id_count']}, chain_conf={row['chain_confidence']}, reason={row['zero_prediction_reason']}"
        )
    lines.extend([
        "",
        "## Diagnosis",
        "- Evidence selection is a major bottleneck when gold evidence is absent or thin in the prompt, but it is not the only bottleneck: several zero-prediction events still have partial gold evidence in the prompt.",
        "- Raising `max_evidence_per_event` from 12 to 16/20 is justified for oracle diagnostics because two events have 13 unique gold evidence IDs, and a 12-evidence cap cannot include all supports.",
        "- Add source balance, stakeholder signal, and gold-like evidence ranking. Current event-chain retrieval is keyword/source-prior based and can miss opinion-bearing support evidence.",
    ])
    if oracle_metrics:
        lines.append(f"- Oracle evidence run currently reports: {oracle_metrics}")
    write_text(AUDIT_DIR / "evidence_coverage_audit.md", "\n".join(lines))
    return summary


def chain_evidence_ids(chain: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for stage in chain.get("stages", []) or []:
        for item in stage.get("evidence", []) or []:
            eid = str(item.get("evidence_id", ""))
            if eid and eid not in ids:
                ids.append(eid)
    return ids


def zero_prediction_reason(gold_ids: list[str], selected: set[str], chain_ids: set[str], chain: dict[str, Any], parse_success: Any) -> str:
    if parse_success is False:
        return "parse_failure"
    if not selected:
        return "no_prompt_evidence"
    if not gold_ids:
        return "no_gold_evidence_refs"
    if not (set(gold_ids) & selected):
        return "gold_evidence_absent_from_prompt"
    if not (set(gold_ids) & chain_ids):
        return "gold_evidence_absent_from_event_chain"
    if float(chain.get("chain_confidence", 0) or 0) < 0.25:
        return "weak_chain_confidence_despite_some_gold_prompt_overlap"
    return "llm_or_prompt_declined_extraction_despite_some_gold_prompt_overlap"


def write_graph_quality_audit(events: list[dict[str, Any]], evidence: list[dict[str, Any]], gold: list[dict[str, Any]], gold_chains: list[dict[str, Any]], chains: list[dict[str, Any]]) -> dict[str, Any]:
    graph = build_stakeholder_event_evidence_graph(events, evidence)
    nodes = graph.node_records()
    edges = graph.edge_records()
    node_types = Counter(str(node.get("node_type", "")) for node in nodes)
    stakeholders_by_event = stakeholder_candidates_by_event(nodes)
    gold_by_event = group_by(gold, "event_id")
    chain_by_event = {str(row.get("event_id")): row for row in chains}
    graph_rows = []
    for event in events:
        event_id = str(event.get("event_id"))
        candidates = stakeholders_by_event.get(event_id, [])
        gold_stakeholders = sorted({str(row.get("stakeholder", "")) for row in gold_by_event.get(event_id, [])})
        overlap = stakeholder_overlap(candidates, gold_stakeholders)
        chain_ids = set(chain_evidence_ids(chain_by_event.get(event_id, {})))
        gold_chain_ids = {eid for row in gold_chains if str(row.get("event_id")) == event_id for eid in evidence_ids(row)}
        graph_rows.append({
            "event_id": event_id,
            "stakeholder_candidate_count": len(candidates),
            "stakeholder_candidates": candidates,
            "gold_stakeholder_count": len(gold_stakeholders),
            "gold_stakeholders": gold_stakeholders,
            "stakeholder_candidate_gold_overlap_count": len(overlap),
            "stakeholder_candidate_gold_overlap": overlap,
            "stage_candidate_count": count_stage_candidates_for_event(nodes, edges, event_id),
            "gold_chain_evidence_overlap_ratio": ratio(len(chain_ids & gold_chain_ids), len(gold_chain_ids)),
        })
    write_csv(AUDIT_DIR / "graph_quality_by_event.csv", graph_rows, list(graph_rows[0].keys()))
    summary = {
        "graph_builder_used": "src/episoa/graph/evidence_graph.py::build_stakeholder_event_evidence_graph",
        "node_type_distribution": dict(node_types),
        "has_stakeholder_candidate_nodes": node_types.get("stakeholder_candidate", 0) > 0,
        "has_temporal_stage_candidate_nodes": node_types.get("temporal_stage_candidate", 0) > 0,
        "has_opinion_or_relation_nodes": any(node_type in {"opinion", "relation", "opinion_relation"} for node_type in node_types),
        "avg_stakeholder_candidates_per_event": round(sum(row["stakeholder_candidate_count"] for row in graph_rows) / len(graph_rows), 4) if graph_rows else 0,
        "avg_gold_stakeholder_overlap_count": round(sum(row["stakeholder_candidate_gold_overlap_count"] for row in graph_rows) / len(graph_rows), 4) if graph_rows else 0,
    }
    lines = [
        "# Graph Quality Audit",
        "",
        f"- Actual graph builder: `{summary['graph_builder_used']}`.",
        f"- Node type distribution: {summary['node_type_distribution']}",
        f"- Stakeholder candidate nodes: {summary['has_stakeholder_candidate_nodes']}",
        f"- Temporal stage candidate nodes: {summary['has_temporal_stage_candidate_nodes']}",
        f"- Opinion/relation nodes: {summary['has_opinion_or_relation_nodes']}",
        "",
        "## Diagnosis",
        "- The current graph is a lightweight event-evidence-source-domain graph plus rule-derived stakeholder/stage candidate nodes.",
        "- It does not extract opinion nodes or stakeholder-opinion relations, and graph content is passed only as candidate hints to schema attribution.",
        "- `without_graph` mainly removes the stakeholder_candidates prompt block; it does not remove a structured reasoning module.",
        "- The graph is therefore too weak to support strong causal claims from the graph ablation.",
        "",
        "## Recommended Graph Experiment",
        "| Setting | Builder | Inputs | Outputs | Purpose |",
        "|---|---|---|---|---|",
        "| no_graph | disabled | events/evidence | empty graph artifacts | baseline |",
        "| graph_rule_based | current evidence_graph.py | events/evidence | stakeholder/stage candidate graph | current approach |",
        "| graph_llm_extracted | proposed model_graph_builder.py | events/evidence + extraction model | stakeholder/opinion/stage/relation graph | test stronger structure |",
        "",
        "A future `model_graph_builder.py` should extract stakeholder, opinion, stage, relation, confidence, and evidence span fields, then feed them as structured constraints instead of loose hints.",
    ]
    write_text(AUDIT_DIR / "graph_quality_audit.md", "\n".join(lines))
    return summary


def write_evaluation_metric_audit(gold: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for matcher in ["exact", "char_jaccard", "char_ngram"]:
        thresholds = [None] if matcher == "exact" else [0.3, 0.4, 0.5, 0.6, 0.7]
        for threshold in thresholds:
            result = metric_result(gold, predictions, matcher=matcher, threshold=threshold or 1.0)
            rows.append({
                "metric": matcher,
                "threshold": "" if threshold is None else threshold,
                "Tuple-F1": result["f1"],
                "Precision": result["precision"],
                "Recall": result["recall"],
                "Sentiment-Acc": result["sentiment_accuracy"],
                "Stakeholder-Recall": result["stakeholder_recall"],
            })
    write_csv(AUDIT_DIR / "evaluation_metric_sensitivity.csv", rows, list(rows[0].keys()))
    baseline = next(row for row in rows if row["metric"] == "char_jaccard" and row["threshold"] == 0.5)
    loose = next(row for row in rows if row["metric"] == "char_jaccard" and row["threshold"] == 0.3)
    summary = {
        "strict_event_id_required": True,
        "one_to_one_matching": True,
        "sentiment_on_matched_only": True,
        "rationale_in_core_f1": False,
        "evidence_support_in_core_f1": False,
        "baseline_char_jaccard_0_5": baseline,
        "loose_char_jaccard_0_3": loose,
    }
    lines = [
        "# Evaluation Metric Audit",
        "",
        "## Code Findings",
        "- `soft_tuple_f1` requires identical `event_id` before any match is considered.",
        "- Matching is greedy one-to-one over candidate pairs sorted by score.",
        "- Stakeholder and opinion are scored by character-level Jaccard; rationale and evidence support are not part of core F1.",
        "- Sentiment accuracy is computed only over matched tuples.",
        "",
        "## Diagnosis",
        f"- Baseline char-Jaccard threshold 0.5 result: {baseline}",
        f"- Lowering char-Jaccard threshold to 0.3 result: {loose}",
        "- If F1 rises sharply at lower thresholds, expression mismatch is a contributor. If it remains low, recall/extraction/evidence coverage dominate.",
        "- Chinese short text can be underestimated by raw character Jaccard when synonyms or normalized stakeholder names differ.",
        "",
        "## Recommendation",
        "- Report a multi-metric table: Strict-F1, Soft-F1, Stakeholder-F1/Recall, Opinion-F1, Evidence-grounded Precision, Recall@K/Coverage.",
        "- Keep Tuple-F1-soft but do not use it as the only headline metric.",
        "- Add a no-API semantic-similarity placeholder only as future work; do not silently call an embedding/LLM service during evaluation.",
    ]
    write_text(AUDIT_DIR / "evaluation_metric_audit.md", "\n".join(lines))
    return summary


def metric_result(gold: list[dict[str, Any]], pred: list[dict[str, Any]], *, matcher: str, threshold: float) -> dict[str, float]:
    pairs: list[tuple[float, int, int, bool]] = []
    for gi, gt in enumerate(gold):
        for pi, pt in enumerate(pred):
            if str(gt.get("event_id")) != str(pt.get("event_id")):
                continue
            if matcher == "exact":
                score = 1.0 if (
                    norm(gt.get("stakeholder")) == norm(pt.get("stakeholder"))
                    and norm(gt.get("opinion")) == norm(pt.get("opinion"))
                    and str(gt.get("sentiment")) == str(pt.get("sentiment"))
                ) else 0.0
            elif matcher == "char_ngram":
                score = 0.5 * ngram_jaccard(str(gt.get("stakeholder", "")), str(pt.get("stakeholder", ""))) + 0.5 * ngram_jaccard(str(gt.get("opinion", "")), str(pt.get("opinion", "")))
            else:
                score = 0.5 * char_jaccard(str(gt.get("stakeholder", "")), str(pt.get("stakeholder", ""))) + 0.5 * char_jaccard(str(gt.get("opinion", "")), str(pt.get("opinion", "")))
            if score >= threshold:
                pairs.append((score, gi, pi, str(gt.get("sentiment")) == str(pt.get("sentiment"))))
    pairs.sort(reverse=True, key=lambda item: item[0])
    matched_g: set[int] = set()
    matched_p: set[int] = set()
    sentiment_correct = 0
    for _score, gi, pi, sent_ok in pairs:
        if gi in matched_g or pi in matched_p:
            continue
        matched_g.add(gi)
        matched_p.add(pi)
        if sent_ok:
            sentiment_correct += 1
    tp = len(matched_p)
    precision = ratio(tp, len(pred))
    recall = ratio(tp, len(gold))
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    stake = stakeholder_recall_custom(gold, pred, matcher=matcher, threshold=threshold if matcher != "exact" else 1.0)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "sentiment_accuracy": round(ratio(sentiment_correct, tp), 4),
        "stakeholder_recall": round(stake, 4),
    }


def stakeholder_recall_custom(gold: list[dict[str, Any]], pred: list[dict[str, Any]], *, matcher: str, threshold: float) -> float:
    pairs: list[tuple[float, int, int]] = []
    for gi, gt in enumerate(gold):
        for pi, pt in enumerate(pred):
            if str(gt.get("event_id")) != str(pt.get("event_id")):
                continue
            if matcher == "exact":
                score = 1.0 if norm(gt.get("stakeholder")) == norm(pt.get("stakeholder")) else 0.0
            elif matcher == "char_ngram":
                score = ngram_jaccard(str(gt.get("stakeholder", "")), str(pt.get("stakeholder", "")))
            else:
                score = char_jaccard(str(gt.get("stakeholder", "")), str(pt.get("stakeholder", "")))
            if score >= threshold:
                pairs.append((score, gi, pi))
    pairs.sort(reverse=True, key=lambda item: item[0])
    matched_g: set[int] = set()
    matched_p: set[int] = set()
    for _score, gi, pi in pairs:
        if gi in matched_g or pi in matched_p:
            continue
        matched_g.add(gi)
        matched_p.add(pi)
    return ratio(len(matched_g), len(gold))


def write_experiment_fairness_audit() -> dict[str, Any]:
    settings = ["full", "without_graph", "without_event_chain", "without_verifier", "without_event_chain_prompt", "without_event_chain_ranking"]
    current_rows = [setting_audit(ROOT / "outputs" / "runs" / f"ablation_{setting}", setting) for setting in settings]
    p0_rows = [setting_audit(P0_FULL_DIR, "p0_full")]
    rows = current_rows + p0_rows
    issues = []
    p0_metrics = read_json(P0_FULL_DIR / "metrics.json")
    current_full_metrics = read_json(OLD_FULL_DIR / "metrics.json")
    if p0_metrics and current_full_metrics and p0_metrics.get("Tuple-F1-soft") != current_full_metrics.get("Tuple-F1-soft"):
        issues.append("P0 full and old full differ; final ablation table should be rerun under P0 parse repair.")
    for row in rows:
        if not row["raw_complete"]:
            issues.append(f"{row['setting']} raw_llm_responses incomplete or missing.")
        if row["parse_failed_count"]:
            issues.append(f"{row['setting']} has parse failures.")
    lines = [
        "# Experiment Fairness Audit",
        "",
        "| Setting | Exists | Events Raw | Predictions | Num Gold | Num Tuples | F1 | Max Tokens | Retries | Parse Failed | Raw Complete |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(f"| {row['setting']} | {row['exists']} | {row['raw_event_count']} | {row['prediction_count']} | {row['num_gold']} | {row['num_tuples']} | {row['tuple_f1']} | {row['max_tokens']} | {row['max_retries']} | {row['parse_failed_count']} | {row['raw_complete']} |")
    lines.extend([
        "",
        "## Issues",
        *(f"- {issue}" for issue in issues),
        "",
        "## Required Answers",
        "- Current ablation table should not be treated as the final paper table until all six settings are rerun under the same P0 parse-repair configuration.",
        "- `without_verifier` ESR/UTR should be N/A; code supports this, but every setting must be regenerated from the same config snapshot.",
        "- Add oracle evidence and model capability probe as diagnostic tables, not as main method comparisons.",
    ])
    write_text(AUDIT_DIR / "experiment_fairness_audit.md", "\n".join(lines))
    return {"rows": rows, "issues": issues}


def setting_audit(setting_dir: Path, setting: str) -> dict[str, Any]:
    metrics = read_json(setting_dir / "metrics.json")
    manifest = read_json(setting_dir / "input_manifest.json")
    raw = read_jsonl(setting_dir / "raw_llm_responses.jsonl")
    pred = read_jsonl(setting_dir / "predictions.jsonl")
    expected_events = int((manifest.get("data") or {}).get("num_events") or 0)
    return {
        "setting": setting,
        "exists": setting_dir.exists(),
        "raw_event_count": len(raw),
        "prediction_count": len(pred),
        "num_gold": metrics.get("Num-Gold", ""),
        "num_tuples": metrics.get("Num-Tuples", ""),
        "tuple_f1": metrics.get("Tuple-F1-soft", ""),
        "max_tokens": (manifest.get("model") or {}).get("max_tokens", ""),
        "max_retries": read_config_snapshot(setting_dir).get("model", {}).get("max_retries", ""),
        "parse_failed_count": sum(1 for row in raw if row.get("parse_success") is False),
        "raw_complete": bool(expected_events and len(raw) == expected_events),
        "event_ids": sorted({str(row.get("event_id")) for row in raw}),
    }


def read_config_snapshot(setting_dir: Path) -> dict[str, Any]:
    path = setting_dir / "config_snapshot.yaml"
    if not path.exists():
        path = setting_dir / "config.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def write_dataset_scale_audit(events: list[dict[str, Any]], evidence: list[dict[str, Any]], gold: list[dict[str, Any]], chains: list[dict[str, Any]]) -> dict[str, Any]:
    ev_by_event = group_by(evidence, "event_id")
    gold_by_event = group_by(gold, "event_id")
    chain_by_event = group_by(chains, "event_id")
    source_dist = Counter(str(row.get("source_type") or row.get("source") or "unknown") for row in evidence)
    domain_dist = Counter(str(row.get("domain") or row.get("platform") or "unknown") for row in evidence)
    event_type_dist = Counter(str(row.get("event_type") or "unknown") for row in events)
    domain_event_dist = Counter(str(row.get("domain") or "unknown") for row in events)
    split_counts = {}
    for split in ["train", "dev", "test"]:
        split_counts[split] = {
            "tuple_identification": len(read_jsonl(BENCHMARK_DIR / "splits" / split / "tuple_identification.jsonl")),
            "evidence_support_classification": len(read_jsonl(BENCHMARK_DIR / "splits" / split / "evidence_support_classification.jsonl")),
            "chain_construction": len(read_jsonl(BENCHMARK_DIR / "splits" / split / "chain_construction.jsonl")),
        }
    summary = {
        "events": len(events),
        "raw_evidence": len(read_jsonl(ROOT / "data" / "pubevent_soa_lite" / "raw" / "raw_posts.jsonl")),
        "clean_evidence": len(evidence),
        "gold_tuples": len(gold),
        "gold_chains": len(chains),
        "split_counts": split_counts,
        "evidence_per_event": describe_values([len(ev_by_event.get(str(event.get("event_id")), [])) for event in events]),
        "gold_tuple_per_event": describe_values([len(gold_by_event.get(str(event.get("event_id")), [])) for event in events]),
        "gold_chain_per_event": describe_values([len(chain_by_event.get(str(event.get("event_id")), [])) for event in events]),
        "source_type_distribution": dict(source_dist),
        "domain_top20": dict(domain_dist.most_common(20)),
        "event_type_distribution": dict(event_type_dist),
        "event_domain_distribution": dict(domain_event_dist),
        "temporal_stage_coverage": dict(Counter(stage for event in events for stage in event.get("temporal_stages", []) or [])),
    }
    lines = [
        "# Dataset Scale Audit",
        "",
        f"- Events: {summary['events']}",
        f"- Raw evidence: {summary['raw_evidence']}",
        f"- Clean evidence: {summary['clean_evidence']}",
        f"- Gold tuples: {summary['gold_tuples']}",
        f"- Gold chains: {summary['gold_chains']}",
        f"- Train/dev/test split counts: {summary['split_counts']}",
        f"- Evidence per event: {summary['evidence_per_event']}",
        f"- Gold tuple per event: {summary['gold_tuple_per_event']}",
        f"- Gold chain per event: {summary['gold_chain_per_event']}",
        f"- Source type distribution: {summary['source_type_distribution']}",
        f"- Event domain distribution: {summary['event_domain_distribution']}",
        "",
        "## Required Answers",
        "- 50 events / 188 tuples is too small for a benchmark-dataset claim in a top-tier paper unless framed as a pilot and backed by strong validation.",
        "- Recommended minimum: 100 events, 300-500 human-adjudicated tuples, 30-35 clean evidence items per event, and 10-15 final gold support evidence items per event.",
        "- Add two independent human annotators, adjudication, and inter-annotator agreement such as Cohen's kappa or Krippendorff's alpha.",
    ]
    write_text(AUDIT_DIR / "dataset_scale_audit.md", "\n".join(lines))
    return summary


def write_oracle_evidence_report(gold: list[dict[str, Any]]) -> None:
    metrics = read_oracle_metrics()
    p0_metrics = read_json(P0_FULL_DIR / "metrics.json")
    raw = read_jsonl(ORACLE_DIR / "ablation_full_oracle_evidence" / "raw_llm_responses.jsonl")
    if not metrics:
        lines = [
            "# Oracle Evidence Report",
            "",
            "Oracle evidence run has not completed yet. Run:",
            "",
            "`python scripts/run_ablation.py --config configs/ablation_oracle_evidence.yaml --force`",
        ]
        write_text(ORACLE_DIR / "oracle_evidence_report.md", "\n".join(lines))
        return
    gold_by_event = group_by(gold, "event_id")
    missing_by_event = {
        str(row.get("event_id")): row.get("request_summary", {}).get("oracle_gold_evidence_missing", [])
        for row in raw
    }
    truncated_events = {event_id: missing for event_id, missing in missing_by_event.items() if missing}
    p0_f1 = float(p0_metrics.get("Tuple-F1-soft", 0) or 0)
    oracle_f1 = float(metrics.get("Tuple-F1-soft", 0) or 0)
    delta = round(oracle_f1 - p0_f1, 4)
    lines = [
        "# Oracle Evidence Report",
        "",
        "## Setup",
        "- Setting: `full_oracle_evidence`.",
        "- Gold tuple text is not provided to the model; only gold evidence IDs are forced into the prompt.",
        "- Non-gold evidence fills remaining slots using the normal selection strategy.",
        "",
        "## Results",
        f"- P0 full Tuple-F1-soft: {p0_metrics.get('Tuple-F1-soft', 'N/A')}",
        f"- full_oracle_evidence Tuple-F1-soft: {metrics.get('Tuple-F1-soft', 'N/A')}",
        f"- Delta: {delta}",
        f"- full_oracle_evidence Precision: {metrics.get('Tuple-Precision', 'N/A')}",
        f"- full_oracle_evidence Recall: {metrics.get('Tuple-Recall', 'N/A')}",
        f"- full_oracle_evidence Num-Tuples: {metrics.get('Num-Tuples', 'N/A')}",
        f"- Events with truncated/missing oracle gold evidence: {truncated_events}",
        "",
        "## Interpretation",
    ]
    if delta >= 0.08:
        lines.append("- Oracle evidence is substantially higher than P0 full; evidence selection / event-chain retrieval is a primary bottleneck.")
    elif delta >= 0.03:
        lines.append("- Oracle evidence improves over P0 full, so evidence selection contributes, but extraction/gold/metric issues remain.")
    else:
        lines.append("- Oracle evidence does not materially improve F1; prioritize LLM extraction, prompt design, gold consistency, and evaluation.")
    lines.extend([
        "",
        "## Coverage Check",
        f"- Events with gold tuples: {len(gold_by_event)}",
        f"- Raw oracle response records: {len(raw)}",
    ])
    write_text(ORACLE_DIR / "oracle_evidence_report.md", "\n".join(lines))


def write_final_report(**kwargs: Any) -> None:
    gold_summary = kwargs["gold_summary"]
    evidence_summary = kwargs["evidence_summary"]
    graph_summary = kwargs["graph_summary"]
    metric_summary = kwargs["metric_summary"]
    fairness_summary = kwargs["fairness_summary"]
    scale_summary = kwargs["scale_summary"]
    oracle_metrics = read_oracle_metrics()
    probe_summary = read_model_probe_summary()
    lines = [
        "# Final Diagnosis Report",
        "",
        "## 1. Executive Summary",
        "Most likely causes of the current F1=0.386 bottleneck, in order:",
        "1. Gold quality / label definition: the configured gold is LLM preannotation, not strict human-verified gold.",
        "2. Evidence selection and event-chain retrieval: prompt gold-evidence overlap is incomplete, especially for zero-prediction events.",
        "3. Prompt/extraction constraints and model behavior: max 4 tuples per event and strict evidence-ID filtering suppress recall.",
        "4. Lightweight graph weakness: current graph gives only rule-based candidate hints and no opinion/relation structure.",
        "5. Metric strictness: character Jaccard can underestimate semantic matches, but metric sensitivity must be interpreted after gold cleanup.",
        "",
        f"- Gold status: {gold_summary['classification']}",
        f"- Avg gold evidence in prompt ratio: {evidence_summary['avg_gold_evidence_in_prompt_ratio']}",
        f"- Current graph has opinion/relation nodes: {graph_summary['has_opinion_or_relation_nodes']}",
        f"- Metric baseline: {metric_summary['baseline_char_jaccard_0_5']}",
        f"- Dataset scale: {scale_summary['events']} events / {scale_summary['gold_tuples']} tuples.",
        "",
        "## 2. Pipeline Map",
        f"See `{rel(AUDIT_DIR / 'pipeline_file_map.md')}` for the complete stage-by-stage input/output table.",
        "",
        "## 3. Gold Quality Diagnosis",
        "- The main experiment reads `llm_gold_tuples.jsonl`, whose `source_type` is `llm_preannotation` and lacks direct human fields.",
        "- The human-reviewed export is auto-reviewed (`auto_reviewer`) with all rows accepted and no edits, so it is not independent human gold.",
        "- Recommendation: relabel current data as silver/pseudo-gold and perform real human review before final paper claims.",
        "",
        "## 4. Evidence Selection Diagnosis",
        f"- Average prompt gold-evidence coverage: {evidence_summary['avg_gold_evidence_in_prompt_ratio']}.",
        f"- Zero-prediction events: {[row['event_id'] for row in evidence_summary['zero_prediction_events']]}",
        f"- Coverage-constrained upper bound from current prompt evidence: {evidence_summary['coverage_constrained_tuple_recall_upper_bound']}.",
    ]
    if oracle_metrics:
        lines.append(f"- Oracle evidence result: {oracle_metrics}.")
    else:
        lines.append("- Oracle evidence result: not available yet or run failed.")
    lines.extend([
        "",
        "## 5. Graph Diagnosis",
        "- Current graph is mostly event/evidence/source/domain plus rule-derived stakeholder and stage nodes.",
        "- It should be upgraded with LLM-extracted stakeholder/opinion/stage/relation nodes and used as structured constraints.",
        "",
        "## 6. LLM Capability Diagnosis",
    ])
    if probe_summary:
        lines.append(f"- Model probe summary: {probe_summary}.")
    else:
        lines.append("- Model capability probe output is not available yet or no API run completed.")
    lines.extend([
        "- Do not conclude current LLM is intrinsically weak until oracle evidence and real gold are both tested.",
        "",
        "## 7. Evaluation Diagnosis",
        "- Current F1 is not pure parse failure after P0; parse failures are zero.",
        "- The metric is strict on event_id and one-to-one matching; it excludes rationale/evidence support from core F1.",
        "- Report multiple metrics rather than a single soft Tuple-F1.",
        "",
        "## 8. Dataset Scale Diagnosis",
        "- 50 events / 188 tuples is too small for a strong benchmark claim.",
        "- Expand to at least 100 events and 300-500 human-adjudicated tuples with double annotation and adjudication.",
        "",
        "## 9. Recommended Fix Plan",
        "### P0: Engineering stability",
        "- Keep P0 parse repair; rerun all six ablations under one config snapshot.",
        "- Store prompt selected evidence, chain evidence, parse status, and verifier status per event.",
        "### P1: Gold human verification",
        "- Replace auto-reviewed LLM labels with real human review, adjudication, provenance, and IAA.",
        "### P2: Evidence selection / oracle evidence",
        "- Use oracle evidence as a diagnostic ceiling, then implement source balance + stakeholder signal + support-evidence reranking.",
        "### P3: Graph upgrade",
        "- Add `model_graph_builder.py` and compare no_graph / graph_rule_based / graph_llm_extracted.",
        "### P4: Stronger model / prompt redesign",
        "- Run 10-event capability probe first, then scale only if it shows material gain.",
        "### P5: Metric redesign and final paper tables",
        "- Report strict, soft, stakeholder, opinion, evidence-grounded precision, recall@K, and coverage metrics.",
        "",
        "## 10. Go/No-Go Decision",
        "- Current result is not ready as a final一区 paper table.",
        "- Minimum go requirements: real human gold, P0-rerun full ablation set, oracle evidence diagnostic, graph-upgrade diagnostic, and multi-metric evaluation.",
        "- Recommended final tables: dataset statistics, gold quality/IAA, main results, ablations, oracle evidence upper bound, model capability probe, metric sensitivity, and error analysis.",
        "",
        "## Report Index",
        f"- `{rel(AUDIT_DIR / 'gold_quality_audit.md')}`",
        f"- `{rel(AUDIT_DIR / 'evidence_coverage_audit.md')}`",
        f"- `{rel(AUDIT_DIR / 'graph_quality_audit.md')}`",
        f"- `{rel(AUDIT_DIR / 'evaluation_metric_audit.md')}`",
        f"- `{rel(AUDIT_DIR / 'experiment_fairness_audit.md')}`",
        f"- `{rel(AUDIT_DIR / 'dataset_scale_audit.md')}`",
    ])
    if fairness_summary["issues"]:
        lines.extend(["", "## Fairness Issues", *(f"- {issue}" for issue in fairness_summary["issues"])])
    write_text(AUDIT_DIR / "final_diagnosis_report.md", "\n".join(lines))


def read_oracle_metrics() -> dict[str, Any]:
    path = ORACLE_DIR / "ablation_results.csv"
    rows = read_csv(path)
    if not rows:
        return {}
    return dict(rows[0])


def read_model_probe_summary() -> dict[str, Any]:
    path = MODEL_PROBE_DIR / "model_capability_probe_results.csv"
    rows = read_csv(path)
    if not rows:
        return {}
    by_model: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_model[row.get("model_name", "")].append(row)
    summary = {}
    for model, model_rows in by_model.items():
        f1s = [float(row.get("Tuple-F1-soft") or 0) for row in model_rows if row.get("scope") == "aggregate"]
        summary[model] = f1s[0] if f1s else ""
    return summary


def count_stage_candidates_for_event(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], event_id: str) -> int:
    evidence_nodes = {node.get("node_id") for node in nodes if node.get("node_type") == "evidence" and (node.get("attributes") or {}).get("event_id") == event_id}
    stage_nodes = {
        edge.get("target_node_id")
        for edge in edges
        if edge.get("source_node_id") in evidence_nodes and edge.get("edge_type") == "indicates_stage"
    }
    return len(stage_nodes)


def stakeholder_overlap(candidates: list[str], gold_stakeholders: list[str]) -> list[str]:
    overlap = []
    for gold in gold_stakeholders:
        for cand in candidates:
            if gold and cand and (gold in cand or cand in gold or char_jaccard(gold, cand) >= 0.45):
                overlap.append(gold)
                break
    return sorted(set(overlap))


def char_jaccard(a: str, b: str) -> float:
    set_a = {ch for ch in str(a) if not ch.isspace()}
    set_b = {ch for ch in str(b) if not ch.isspace()}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def ngram_jaccard(a: str, b: str) -> float:
    set_a = set(chinese_ngrams(a, n=2))
    set_b = set(chinese_ngrams(b, n=2))
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def chinese_ngrams(text: str, n: int = 2) -> list[str]:
    chars = [ch for ch in str(text) if not ch.isspace()]
    if len(chars) <= n:
        return ["".join(chars)] if chars else []
    return ["".join(chars[i:i + n]) for i in range(len(chars) - n + 1)]


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def ratio(num: int | float, den: int | float) -> float:
    return round(float(num) / float(den), 4) if den else 0.0


def excerpt(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


if __name__ == "__main__":
    raise SystemExit(main())
