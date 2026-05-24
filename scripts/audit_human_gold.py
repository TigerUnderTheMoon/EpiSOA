#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit human_gold_v1 JSONL outputs and update readiness manifest."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DIR = Path("data/pubevent_soa_lite/human_gold_v1")
DEFAULT_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events.jsonl")
VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed", "unknown"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tuples_path = Path(args.tuples)
    chains_path = Path(args.chains)
    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    if args.pilot:
        if tuples_path == DEFAULT_DIR / "human_gold_tuples_v1.jsonl":
            tuples_path = output_dir / "pilot_human_gold_tuples_v1.jsonl"
        if chains_path == DEFAULT_DIR / "human_gold_event_chains_v1.jsonl":
            chains_path = output_dir / "pilot_human_gold_event_chains_v1.jsonl"
        if manifest_path == DEFAULT_DIR / "human_gold_manifest_v1.json":
            manifest_path = output_dir / "pilot_human_gold_manifest_v1.json"
    report = audit_human_gold(
        tuples_path=tuples_path,
        chains_path=chains_path,
        evidence_path=Path(args.evidence),
        events_path=Path(args.events),
        manifest_path=manifest_path,
        output_dir=output_dir,
        report_prefix="pilot_human_gold" if args.pilot else "human_gold",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["total_issues"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit human_gold_v1 outputs.")
    parser.add_argument("--tuples", default=str(DEFAULT_DIR / "human_gold_tuples_v1.jsonl"))
    parser.add_argument("--chains", default=str(DEFAULT_DIR / "human_gold_event_chains_v1.jsonl"))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--manifest", default=str(DEFAULT_DIR / "human_gold_manifest_v1.json"))
    parser.add_argument("--output-dir", default=str(DEFAULT_DIR))
    parser.add_argument("--pilot", action="store_true", help="Audit pilot_human_gold_* outputs instead of formal human_gold_v1 outputs.")
    return parser


def audit_human_gold(
    *,
    tuples_path: Path,
    chains_path: Path,
    evidence_path: Path,
    events_path: Path,
    manifest_path: Path,
    output_dir: Path,
    report_prefix: str = "human_gold",
) -> dict[str, Any]:
    tuples = read_jsonl(tuples_path)
    chains = read_jsonl(chains_path)
    evidence = read_jsonl(evidence_path)
    events = read_jsonl(events_path)
    manifest = read_json(manifest_path)
    event_ids = {str(row.get("event_id")) for row in events if row.get("event_id")}
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}

    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    audit_tuples(tuples, chains, event_ids, evidence_by_id, issues, warnings)
    audit_chains(chains, tuples, event_ids, evidence_by_id, issues, manifest)
    if not tuples:
        issues.append({"severity": "error", "check": "nonempty_tuples", "message": "human_gold_tuples_v1 is empty"})
    if not chains:
        issues.append({"severity": "error", "check": "nonempty_chains", "message": "human_gold_event_chains_v1 is empty"})

    total_issues = len(issues)
    ready = total_issues == 0
    report = {
        "valid": ready,
        "ready_for_main_experiment": ready,
        "total_issues": total_issues,
        "total_warnings": len(warnings),
        "issue_counts": dict(Counter(issue["check"] for issue in issues)),
        "warning_counts": dict(Counter(warning["check"] for warning in warnings)),
        "issues": issues,
        "warnings": warnings,
        "counts": {
            "human_gold_tuples": len(tuples),
            "human_gold_event_chains": len(chains),
            "events_with_tuples": len({row.get("event_id") for row in tuples}),
            "events_with_chains": len({row.get("event_id") for row in chains}),
            "evidence_records": len(evidence),
            "events": len(events),
        },
        "audit_appendix": {
            "error_type_distribution": dict(Counter(issue["check"] for issue in issues)),
            "warning_type_distribution": dict(Counter(warning["check"] for warning in warnings)),
            "typical_issue_cases": issues[:10],
            "typical_warning_cases": warnings[:10],
        },
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / f"{report_prefix}_audit.json", report)
    write_text(output_dir / f"{report_prefix}_audit.md", render_markdown(report))
    write_json(output_dir / f"{report_prefix}_audit_report.json", report)
    write_text(output_dir / f"{report_prefix}_audit_report.md", render_appendix_markdown(report))
    update_manifest(manifest_path, report, output_dir / f"{report_prefix}_audit.json")
    return report


def audit_tuples(
    tuples: list[dict[str, Any]],
    chains: list[dict[str, Any]],
    event_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str, str, tuple[str, ...]]] = set()
    chain_ids = {str(row.get("chain_id")) for row in chains if row.get("chain_id")}
    chain_evidence_by_id = {
        str(row.get("chain_id")): {str(item) for item in row.get("evidence_ids", []) or []}
        for row in chains
        if row.get("chain_id")
    }
    chain_evidence_by_event: dict[str, set[str]] = defaultdict(set)
    for row in chains:
        chain_evidence_by_event[str(row.get("event_id") or "")].update(str(item) for item in row.get("evidence_ids", []) or [])
    for index, row in enumerate(tuples, start=1):
        prefix = row.get("tuple_id") or f"row_{index}"
        tuple_id = str(row.get("tuple_id") or "")
        if not tuple_id:
            issues.append(issue("tuple_id_nonempty", prefix, "tuple_id is empty"))
        elif tuple_id in seen_ids:
            issues.append(issue("duplicate_tuple_id", prefix, tuple_id))
        seen_ids.add(tuple_id)
        event_id = str(row.get("event_id") or "")
        if event_id not in event_ids:
            issues.append(issue("tuple_event_id_exists", prefix, event_id))
        for field in ("stakeholder", "opinion", "rationale"):
            if not str(row.get(field) or "").strip():
                issues.append(issue(f"tuple_{field}_nonempty", prefix, f"{field} is empty"))
        if row.get("sentiment") not in VALID_SENTIMENTS:
            issues.append(issue("tuple_sentiment_valid", prefix, str(row.get("sentiment"))))
        ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        if not ids:
            issues.append(issue("tuple_evidence_ids_nonempty", prefix, "missing evidence_ids"))
        for evidence_id in ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                issues.append(issue("tuple_evidence_id_exists", prefix, str(evidence_id)))
            elif str(evidence.get("event_id")) != event_id:
                issues.append(issue("tuple_evidence_same_event", prefix, str(evidence_id)))
        key = (
            event_id,
            str(row.get("stakeholder") or "").strip().lower(),
            str(row.get("opinion") or "").strip().lower(),
            str(row.get("sentiment") or ""),
            tuple(sorted(str(item) for item in ids)),
        )
        if key in seen_keys:
            issues.append(issue("duplicate_tuple_content", prefix, "|".join(key[:4])))
        seen_keys.add(key)
        referenced_chain_ids = tuple_chain_ids(row)
        provenance = row.get("annotation_provenance") if isinstance(row.get("annotation_provenance"), dict) else {}
        if str(provenance.get("adjudication_status") or "").strip() != "adjudicated_final":
            issues.append(issue("tuple_adjudicated_final", prefix, "annotation_provenance.adjudication_status must be adjudicated_final"))
        if not str(provenance.get("reviewer_id") or "").strip():
            issues.append(issue("tuple_human_reviewer_present", prefix, "missing reviewer_id in annotation_provenance"))
        if str(provenance.get("reviewer_id") or "").strip() == "auto_reviewer":
            issues.append(issue("tuple_human_reviewer_not_auto", prefix, "auto_reviewer is not allowed in human gold"))
        for chain_id in referenced_chain_ids:
            if chain_id not in chain_ids:
                issues.append(issue("tuple_chain_id_exists", prefix, f"unknown chain_id {chain_id}"))
        tuple_evidence = {str(item) for item in ids}
        if referenced_chain_ids:
            for chain_id in referenced_chain_ids:
                chain_evidence = chain_evidence_by_id.get(chain_id, set())
                if chain_evidence and tuple_evidence and not (tuple_evidence & chain_evidence):
                    warnings.append(warning("tuple_chain_evidence_overlap", prefix, f"no evidence overlap with chain_id {chain_id}"))
        elif chain_evidence_by_event.get(event_id) and tuple_evidence and not (tuple_evidence & chain_evidence_by_event[event_id]):
            warnings.append(warning("tuple_event_chain_evidence_overlap", prefix, "no evidence overlap with any same-event chain"))


def audit_chains(
    chains: list[dict[str, Any]],
    tuples: list[dict[str, Any]],
    event_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    tuple_events = {str(row.get("event_id")) for row in tuples if row.get("event_id")}
    allow_orphan_chains = bool(manifest.get("allow_orphan_chains", False))
    seen_ids: set[str] = set()
    for index, row in enumerate(chains, start=1):
        prefix = row.get("chain_id") or f"row_{index}"
        chain_id = str(row.get("chain_id") or "")
        if not chain_id:
            issues.append(issue("chain_id_nonempty", prefix, "chain_id is empty"))
        elif chain_id in seen_ids:
            issues.append(issue("duplicate_chain_id", prefix, chain_id))
        seen_ids.add(chain_id)
        event_id = str(row.get("event_id") or "")
        if event_id not in event_ids:
            issues.append(issue("chain_event_id_exists", prefix, event_id))
        if event_id and event_id not in tuple_events and not allow_orphan_chains:
            issues.append(issue("orphan_chain", prefix, f"no human gold tuples for event {event_id}"))
        nodes = row.get("event_chain") if isinstance(row.get("event_chain"), list) else []
        if not nodes:
            issues.append(issue("chain_nodes_nonempty", prefix, "missing event_chain"))
        ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        if not ids:
            issues.append(issue("chain_evidence_ids_nonempty", prefix, "missing evidence_ids"))
        for evidence_id in ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                issues.append(issue("chain_evidence_id_exists", prefix, str(evidence_id)))
            elif str(evidence.get("event_id")) != event_id:
                issues.append(issue("chain_evidence_same_event", prefix, str(evidence_id)))
        provenance = row.get("annotation_provenance") if isinstance(row.get("annotation_provenance"), dict) else {}
        if str(provenance.get("adjudication_status") or "").strip() != "adjudicated_final":
            issues.append(issue("chain_adjudicated_final", prefix, "annotation_provenance.adjudication_status must be adjudicated_final"))
        if not str(provenance.get("reviewer_id") or "").strip():
            issues.append(issue("chain_human_reviewer_present", prefix, "missing reviewer_id in annotation_provenance"))
        if str(provenance.get("reviewer_id") or "").strip() == "auto_reviewer":
            issues.append(issue("chain_human_reviewer_not_auto", prefix, "auto_reviewer is not allowed in human gold"))


def issue(check: str, row: str, message: str) -> dict[str, str]:
    return {"severity": "error", "check": check, "row": row, "message": message}


def warning(check: str, row: str, message: str) -> dict[str, str]:
    return {"severity": "warning", "check": check, "row": row, "message": message}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    backup_existing(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    backup_existing(path)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def backup_existing(path: Path) -> None:
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_{timestamp}"))


def update_manifest(path: Path, report: dict[str, Any], audit_path: Path) -> None:
    manifest: dict[str, Any] = {}
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["ready_for_main_experiment"] = report["ready_for_main_experiment"]
    manifest["last_audit"] = {
        "path": str(audit_path),
        "total_issues": report["total_issues"],
        "audited_at": report["audited_at"],
    }
    write_json(path, manifest)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Human Gold Audit",
        "",
        f"- ready_for_main_experiment: {report['ready_for_main_experiment']}",
        f"- total_issues: {report['total_issues']}",
        f"- total_warnings: {report['total_warnings']}",
        f"- counts: {report['counts']}",
        f"- issue_counts: {report['issue_counts']}",
        f"- warning_counts: {report['warning_counts']}",
        "",
        "## Issues",
    ]
    if not report["issues"]:
        lines.append("- No issues found.")
    else:
        for item in report["issues"][:200]:
            lines.append(f"- {item['check']} / {item['row']}: {item['message']}")
    lines.append("")
    lines.append("## Warnings")
    if not report["warnings"]:
        lines.append("- No warnings.")
    else:
        for item in report["warnings"][:200]:
            lines.append(f"- {item['check']} / {item['row']}: {item['message']}")
    return "\n".join(lines)


def render_appendix_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Human Gold Audit Report",
        "",
        "## Summary",
        f"- ready_for_main_experiment: {report['ready_for_main_experiment']}",
        f"- total_issues: {report['total_issues']}",
        f"- total_warnings: {report['total_warnings']}",
        f"- counts: {report['counts']}",
        "",
        "## Error Type Distribution",
    ]
    for key, count in sorted(report["audit_appendix"]["error_type_distribution"].items()):
        lines.append(f"- {key}: {count}")
    if not report["audit_appendix"]["error_type_distribution"]:
        lines.append("- No errors.")
    lines.extend(["", "## Warning Type Distribution"])
    for key, count in sorted(report["audit_appendix"]["warning_type_distribution"].items()):
        lines.append(f"- {key}: {count}")
    if not report["audit_appendix"]["warning_type_distribution"]:
        lines.append("- No warnings.")
    lines.extend(["", "## Typical Issue Cases"])
    for item in report["audit_appendix"]["typical_issue_cases"]:
        lines.append(f"- {item.get('check', '')} / {item.get('row', 'dataset')}: {item.get('message', '')}")
    if not report["audit_appendix"]["typical_issue_cases"]:
        lines.append("- No issue cases.")
    return "\n".join(lines)


def tuple_chain_ids(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("chain_id", "event_chain_id"):
        value = row.get(field)
        if value:
            values.append(str(value))
    raw_chain_ids = row.get("chain_ids")
    if isinstance(raw_chain_ids, list):
        values.extend(str(item) for item in raw_chain_ids if str(item))
    elif raw_chain_ids:
        values.extend(part.strip() for part in str(raw_chain_ids).replace("|", ";").replace(",", ";").split(";") if part.strip())
    return list(dict.fromkeys(values))


if __name__ == "__main__":
    raise SystemExit(main())
