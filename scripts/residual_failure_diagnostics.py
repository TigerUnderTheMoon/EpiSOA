"""Generate residual failure diagnostics for a collector run directory."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from typing import Any

from episoa.collector.coverage_extractor import (
    STANCE_RULES,
    TEMPORAL_STAGE_RULES,
    classify_source,
    evaluate_event_coverage,
    extract_rule_evidence,
)
from episoa.data.loader import read_jsonl


DEFAULT_EVENTS = Path("data/pubevent_soa_lite/events_smoke_10.jsonl")
DEFAULT_RUN_DIR = Path("outputs/runs/collector_smoke_10_official_fix")
STANCE_CANDIDATE_TERMS = [
    "居民反映",
    "业主反映",
    "群众反映",
    "市民反映",
    "被投诉",
    "引发质疑",
    "引发争议",
    "引发不满",
    "担心影响",
    "认为不合理",
    "要求公开",
    "要求解释",
    "要求处理",
    "要求整改",
    "多次反映",
    "反映无果",
    "相关部门表示",
    "工作人员表示",
    "官方回应称",
    "已回复",
    "已受理",
    "已办结",
    "正在协调",
    "正在处理",
    "将督促",
    "将整改",
    "已责令",
    "已约谈",
    "已核查",
    "经核实",
    "情况属实",
    "情况不属实",
    "居民点赞",
    "获得认可",
    "表示满意",
    "方便居民",
    "改善环境",
    "提升品质",
    "有助于",
    "得到支持",
]
TEMPORAL_CANDIDATE_TERMS = [
    "征集意见",
    "征求意见稿",
    "初步方案",
    "专项规划",
    "纳入计划",
    "列入改造计划",
    "项目公示",
    "批前公示",
    "批后公告",
    "招标计划",
    "已进场",
    "正在施工",
    "正在推进",
    "完成施工",
    "施工期间",
    "改造现场",
    "开展整治",
    "组织实施",
    "引发争议",
    "引发投诉",
    "居民担忧",
    "群众反映",
    "业主维权",
    "协商未果",
    "产生矛盾",
    "部门回应",
    "街道回应",
    "平台回复",
    "已受理",
    "正在核实",
    "正在协调",
    "已派人处理",
    "将进一步处理",
    "完成整改",
    "已整改",
    "整改到位",
    "问题解决",
    "达成一致",
    "调整方案",
    "暂停施工",
    "恢复施工",
    "已办结",
    "后续跟进",
    "持续跟踪",
    "建立长效机制",
    "继续推进",
    "后续安排",
    "回访居民",
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = Path(args.run_dir)
    output_dir = Path(args.output_dir) if args.output_dir else run_dir / "residual_diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)
    events = read_jsonl(args.events)
    raw_rows = read_jsonl(run_dir / "raw_posts.jsonl")
    coverage = _read_json(run_dir / "coverage.json")
    qc_report = _read_json(run_dir / "post_collect_qc" / "post_collect_qc_report.json")
    repair_summary = _read_json(run_dir / "repair_collection_summary.json")

    events_by_id = {str(event.get("event_id")): event for event in events}
    raw_by_event = _group_by_event(raw_rows)
    failed_ids = [str(row.get("event_id")) for row in qc_report.get("events_need_recollection", [])]
    provider_errors = _provider_error_rows(coverage, repair_summary)
    provider_error_counts = Counter(row["event_id"] for row in provider_errors)
    coverage_by_event = {
        event_id: evaluate_event_coverage(events_by_id.get(event_id, {"event_id": event_id}), raw_by_event.get(event_id, []))
        for event_id in failed_ids
    }

    failed_rows = [
        {
            "event_id": event_id,
            "raw_count": len(raw_by_event.get(event_id, [])),
            "missing_sources": "|".join(coverage_by_event[event_id].get("missing_sources") or []),
            "missing_stakeholders": "|".join(coverage_by_event[event_id].get("missing_stakeholders") or []),
            "missing_stances": "|".join(coverage_by_event[event_id].get("missing_stances") or []),
            "missing_temporal_stages": "|".join(coverage_by_event[event_id].get("missing_temporal_stages") or []),
            "provider_errors_count": provider_error_counts[event_id],
            "suspected_failure_type": _suspected_failure_type(event_id, raw_by_event, coverage_by_event[event_id], provider_error_counts[event_id]),
        }
        for event_id in failed_ids
    ]
    _write_csv(output_dir / "failed_events_summary.csv", list(failed_rows[0]) if failed_rows else _failed_fields(), failed_rows)

    matrix_rows = []
    stance_candidate_rows = []
    temporal_candidate_rows = []
    for event_id in failed_ids:
        for raw in raw_by_event.get(event_id, []):
            stance_rows = extract_rule_evidence([raw], STANCE_RULES, "stance_type")
            temporal_rows = extract_rule_evidence([raw], TEMPORAL_STAGE_RULES, "stage_type")
            stakeholder_rows = evaluate_event_coverage(events_by_id.get(event_id, {"event_id": event_id}), [raw]).get("stakeholder_evidence", [])
            stance_hits = _term_hits(raw, STANCE_CANDIDATE_TERMS)
            temporal_hits = _term_hits(raw, TEMPORAL_CANDIDATE_TERMS)
            matrix_rows.append(
                {
                    "event_id": event_id,
                    "raw_id": raw.get("raw_id", ""),
                    "detected_source_type": classify_source(raw).get("detected_source_type"),
                    "covered_stakeholders": "|".join(sorted({row["stakeholder_type"] for row in stakeholder_rows if row.get("rule_strength") == "strong"})),
                    "covered_stances": "|".join(sorted({row["stance_type"] for row in stance_rows if row.get("rule_strength") == "strong"})),
                    "covered_temporal_stages": "|".join(sorted({row["stage_type"] for row in temporal_rows if row.get("rule_strength") == "strong"})),
                    "matched_keywords": "|".join(stance_hits + temporal_hits),
                    "extractor_debug_reason": _extractor_debug_reason(stance_hits, temporal_hits, stance_rows, temporal_rows),
                }
            )
            if event_id in {"E001", "E007"} and stance_hits:
                counted = bool([row for row in stance_rows if row.get("rule_strength") == "strong" and row.get("stance_type") != "neutral_report"])
                stance_candidate_rows.append(_candidate_row(raw, stance_hits, classify_source(raw), counted))
            if event_id == "E007" and temporal_hits:
                counted = bool([row for row in temporal_rows if row.get("rule_strength") == "strong"])
                temporal_candidate_rows.append(_temporal_candidate_row(raw, temporal_hits, counted))

    _write_csv(output_dir / "event_raw_coverage_matrix.csv", _matrix_fields(), matrix_rows)
    _write_csv(output_dir / "missing_stance_candidates.csv", _stance_candidate_fields(), stance_candidate_rows)
    _write_csv(output_dir / "missing_temporal_candidates.csv", _temporal_candidate_fields(), temporal_candidate_rows)
    _write_csv(output_dir / "provider_error_summary.csv", _provider_error_fields(), [row for row in provider_errors if row["event_id"] in failed_ids])
    _write_csv(output_dir / "cap_dedupe_loss_report.csv", _cap_fields(), _cap_rows(repair_summary, failed_ids))
    print(f"residual diagnostics written: {output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write residual failure diagnostics for a collector run.")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--output-dir", default="")
    return parser


def _suspected_failure_type(event_id: str, raw_by_event: dict[str, list[dict[str, Any]]], coverage: dict[str, Any], provider_errors: int) -> str:
    raw_count = len(raw_by_event.get(event_id, []))
    if raw_count < 15 and provider_errors:
        return "provider_instability"
    if raw_count < 15:
        return "query_hit_shortfall"
    if coverage.get("missing_stances") and _unmapped_candidate_exists(raw_by_event.get(event_id, []), STANCE_CANDIDATE_TERMS, STANCE_RULES, "stance_type"):
        return "extractor_miss_or_qc_threshold_mismatch"
    if coverage.get("missing_temporal_stages") and _unmapped_candidate_exists(raw_by_event.get(event_id, []), TEMPORAL_CANDIDATE_TERMS, TEMPORAL_STAGE_RULES, "stage_type"):
        return "extractor_miss_or_qc_threshold_mismatch"
    if coverage.get("missing_stances") or coverage.get("missing_temporal_stages"):
        return "true_evidence_missing"
    return "unknown"


def _unmapped_candidate_exists(
    rows: list[dict[str, Any]], terms: list[str], rules: tuple[Any, ...], label_key: str
) -> bool:
    for row in rows:
        if _term_hits(row, terms) and not extract_rule_evidence([row], rules, label_key):
            return True
    return False


def _provider_error_rows(coverage: dict[str, Any], repair_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in coverage.get("errors", []):
        rows.append(
            {
                "event_id": row.get("event_id", ""),
                "query": row.get("query", ""),
                "source_type": row.get("source_type") or row.get("target_source") or "",
                "provider": row.get("provider", "search_client"),
                "error_type": row.get("error_type", ""),
                "duration_seconds": row.get("duration_seconds", ""),
                "retry_count": row.get("retry_count", ""),
                "final_status": row.get("final_status", "failed"),
            }
        )
    for event in repair_summary.get("events", {}).values():
        for attempt in [*event.get("first_pass_attempts", []), *event.get("repair_attempts", [])]:
            if attempt.get("ok") is False:
                rows.append(
                    {
                        "event_id": attempt.get("event_id", ""),
                        "query": attempt.get("query", ""),
                        "source_type": attempt.get("source_type", ""),
                        "provider": attempt.get("provider", "search_client"),
                        "error_type": attempt.get("error_type", ""),
                        "duration_seconds": attempt.get("duration_seconds", ""),
                        "retry_count": attempt.get("retry_count", ""),
                        "final_status": attempt.get("final_status", "failed"),
                    }
                )
    return rows


def _cap_rows(repair_summary: dict[str, Any], failed_ids: list[str]) -> list[dict[str, Any]]:
    rows = []
    for event in repair_summary.get("events", {}).values():
        for attempt in [*event.get("first_pass_attempts", []), *event.get("repair_attempts", [])]:
            if str(attempt.get("event_id")) not in failed_ids:
                continue
            dropped = int(attempt.get("result_count") or 0) - int(attempt.get("written") or 0)
            if dropped <= 0:
                continue
            rows.append(
                {
                    "event_id": attempt.get("event_id", ""),
                    "query": attempt.get("query", ""),
                    "candidate_url": "",
                    "detected_source_type": attempt.get("source_type", ""),
                    "dropped_reason": "dedupe_or_cap_untraced",
                    "duplicate_of": "",
                    "cap_bucket": attempt.get("source_type", ""),
                }
            )
    return rows


def _candidate_row(raw: dict[str, Any], hits: list[str], source_debug: dict[str, Any], counted: bool) -> dict[str, Any]:
    return {
        "raw_id": raw.get("raw_id", ""),
        "title/snippet/text excerpt": _excerpt(raw),
        "detected_source_type": source_debug.get("detected_source_type", ""),
        "possible_stance_keywords": "|".join(hits),
        "whether_counted_by_extractor": counted,
        "why_not_counted": "" if counted else "candidate keyword not mapped to strong non-neutral stance",
    }


def _temporal_candidate_row(raw: dict[str, Any], hits: list[str], counted: bool) -> dict[str, Any]:
    return {
        "raw_id": raw.get("raw_id", ""),
        "title/snippet/text excerpt": _excerpt(raw),
        "possible_temporal_keywords": "|".join(hits),
        "whether_counted_by_extractor": counted,
        "why_not_counted": "" if counted else "candidate keyword not mapped to strong temporal stage",
    }


def _extractor_debug_reason(stance_hits: list[str], temporal_hits: list[str], stance_rows: list[dict[str, Any]], temporal_rows: list[dict[str, Any]]) -> str:
    reasons = []
    if stance_hits and not stance_rows:
        reasons.append("stance_candidate_not_counted")
    if temporal_hits and not temporal_rows:
        reasons.append("temporal_candidate_not_counted")
    if not reasons:
        reasons.append("no_unmapped_candidate")
    return "; ".join(reasons)


def _event_term_hits(rows: list[dict[str, Any]], terms: list[str]) -> list[str]:
    hits: list[str] = []
    for row in rows:
        hits.extend(_term_hits(row, terms))
    return sorted(set(hits))


def _term_hits(row: dict[str, Any], terms: list[str]) -> list[str]:
    text = " ".join(str(row.get(key) or "") for key in ("title", "snippet", "text"))
    return [term for term in terms if term in text]


def _excerpt(row: dict[str, Any], limit: int = 220) -> str:
    text = " ".join(str(row.get(key) or "") for key in ("title", "snippet", "text"))
    return " ".join(text.split())[:limit]


def _group_by_event(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("event_id") or "")].append(row)
    return dict(grouped)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _failed_fields() -> list[str]:
    return ["event_id", "raw_count", "missing_sources", "missing_stakeholders", "missing_stances", "missing_temporal_stages", "provider_errors_count", "suspected_failure_type"]


def _matrix_fields() -> list[str]:
    return ["event_id", "raw_id", "detected_source_type", "covered_stakeholders", "covered_stances", "covered_temporal_stages", "matched_keywords", "extractor_debug_reason"]


def _stance_candidate_fields() -> list[str]:
    return ["raw_id", "title/snippet/text excerpt", "detected_source_type", "possible_stance_keywords", "whether_counted_by_extractor", "why_not_counted"]


def _temporal_candidate_fields() -> list[str]:
    return ["raw_id", "title/snippet/text excerpt", "possible_temporal_keywords", "whether_counted_by_extractor", "why_not_counted"]


def _provider_error_fields() -> list[str]:
    return ["event_id", "query", "source_type", "provider", "error_type", "duration_seconds", "retry_count", "final_status"]


def _cap_fields() -> list[str]:
    return ["event_id", "query", "candidate_url", "detected_source_type", "dropped_reason", "duplicate_of", "cap_bucket"]


if __name__ == "__main__":
    raise SystemExit(main())
