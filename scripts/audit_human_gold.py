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
    report = audit_human_gold(
        tuples_path=Path(args.tuples),
        chains_path=Path(args.chains),
        evidence_path=Path(args.evidence),
        events_path=Path(args.events),
        manifest_path=Path(args.manifest),
        output_dir=Path(args.output_dir),
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
    return parser


def audit_human_gold(
    *,
    tuples_path: Path,
    chains_path: Path,
    evidence_path: Path,
    events_path: Path,
    manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    tuples = read_jsonl(tuples_path)
    chains = read_jsonl(chains_path)
    evidence = read_jsonl(evidence_path)
    events = read_jsonl(events_path)
    event_ids = {str(row.get("event_id")) for row in events if row.get("event_id")}
    evidence_by_id = {str(row.get("evidence_id")): row for row in evidence if row.get("evidence_id")}

    issues: list[dict[str, Any]] = []
    audit_tuples(tuples, event_ids, evidence_by_id, issues)
    audit_chains(chains, tuples, event_ids, evidence_by_id, issues)
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
        "issue_counts": dict(Counter(issue["check"] for issue in issues)),
        "issues": issues,
        "counts": {
            "human_gold_tuples": len(tuples),
            "human_gold_event_chains": len(chains),
            "events_with_tuples": len({row.get("event_id") for row in tuples}),
            "events_with_chains": len({row.get("event_id") for row in chains}),
            "evidence_records": len(evidence),
            "events": len(events),
        },
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "human_gold_audit.json", report)
    write_text(output_dir / "human_gold_audit.md", render_markdown(report))
    update_manifest(manifest_path, report)
    return report


def audit_tuples(
    tuples: list[dict[str, Any]],
    event_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str, str, tuple[str, ...]]] = set()
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


def audit_chains(
    chains: list[dict[str, Any]],
    tuples: list[dict[str, Any]],
    event_ids: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    tuple_events = {str(row.get("event_id")) for row in tuples if row.get("event_id")}
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
        if event_id and event_id not in tuple_events:
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


def issue(check: str, row: str, message: str) -> dict[str, str]:
    return {"severity": "error", "check": check, "row": row, "message": message}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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


def update_manifest(path: Path, report: dict[str, Any]) -> None:
    manifest: dict[str, Any] = {}
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["ready_for_main_experiment"] = report["ready_for_main_experiment"]
    manifest["last_audit"] = {
        "path": str(path.parent / "human_gold_audit.json"),
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
        f"- counts: {report['counts']}",
        f"- issue_counts: {report['issue_counts']}",
        "",
        "## Issues",
    ]
    if not report["issues"]:
        lines.append("- No issues found.")
    else:
        for item in report["issues"][:200]:
            lines.append(f"- {item['check']} / {item['row']}: {item['message']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
