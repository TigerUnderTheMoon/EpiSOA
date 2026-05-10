"""Analyze paired heuristic-vs-GA query planner ablation outputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FOCUS_METRICS = [
    "initial_entity_coverage",
    "initial_source_coverage",
    "initial_need_query_repair",
    "num_repair_rounds",
    "num_repair_queries",
    "final_entity_coverage",
    "final_source_coverage",
    "total_api_calls",
    "probe_api_calls",
]

NUMERIC_METRICS = [
    "initial_source_coverage",
    "initial_entity_coverage",
    "initial_traceability_rate",
    "initial_redundancy_rate",
    "initial_need_query_repair",
    "final_source_coverage",
    "final_entity_coverage",
    "final_traceability_rate",
    "final_redundancy_rate",
    "num_raw_posts",
    "num_repair_rounds",
    "num_repair_queries",
    "total_collection_queries",
    "total_api_calls",
    "probe_api_calls",
    "cache_hits",
    "cache_misses",
    "repair_api_calls",
    "evidence_per_api_call",
    "coverage_gain_per_api_call",
]

DIFF_COLUMNS = [
    "event_id",
    "ga_value_score",
    *[f"{metric}_diff" for metric in NUMERIC_METRICS],
]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = analyze_ablation(
        per_event_path=Path(args.per_event),
        summary_path=Path(args.summary),
        output_dir=Path(args.output_dir),
        top_k=args.top_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze query planner ablation CSV outputs.")
    parser.add_argument("--per-event", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    return parser


def analyze_ablation(*, per_event_path: Path, summary_path: Path, output_dir: Path, top_k: int = 10) -> dict[str, Any]:
    rows = _read_csv(per_event_path)
    summary_rows = _read_csv(summary_path)
    paired = _paired_differences(rows)
    ranked = sorted(paired, key=lambda row: float(row["ga_value_score"]), reverse=True)
    helps = ranked[:top_k]
    hurts = list(reversed(ranked[-top_k:]))
    aggregate = _aggregate_diagnostics(paired)
    result = {
        "status": "completed",
        "num_events": len(paired),
        "input_per_event": str(per_event_path),
        "input_summary": str(summary_path),
        "aggregate_diagnostics": aggregate,
        "summary_conditions": [row.get("condition") for row in summary_rows],
        "outputs": {
            "paired_differences": str(output_dir / "query_planner_ablation_paired_differences.csv"),
            "ga_helps_most": str(output_dir / "query_planner_ablation_ga_helps_most.csv"),
            "ga_hurts_most": str(output_dir / "query_planner_ablation_ga_hurts_most.csv"),
            "json_summary": str(output_dir / "query_planner_ablation_analysis_summary.json"),
            "markdown_report": str(output_dir / "query_planner_ablation_analysis.md"),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "query_planner_ablation_paired_differences.csv", paired, DIFF_COLUMNS)
    _write_csv(output_dir / "query_planner_ablation_ga_helps_most.csv", helps, DIFF_COLUMNS)
    _write_csv(output_dir / "query_planner_ablation_ga_hurts_most.csv", hurts, DIFF_COLUMNS)
    _write_json(output_dir / "query_planner_ablation_analysis_summary.json", result)
    _write_markdown(output_dir / "query_planner_ablation_analysis.md", result, helps, hurts)
    return result


def _paired_differences(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_event: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        by_event.setdefault(row["event_id"], {})[row["condition"]] = row
    output = []
    for event_id in sorted(by_event):
        pair = by_event[event_id]
        if set(pair) != {"heuristic", "ga"}:
            raise ValueError(f"event {event_id} does not have exactly one heuristic and one ga row")
        row: dict[str, Any] = {"event_id": event_id}
        for metric in NUMERIC_METRICS:
            row[f"{metric}_diff"] = _float(pair["ga"][metric]) - _float(pair["heuristic"][metric])
        row["ga_value_score"] = _ga_value_score(row)
        output.append(row)
    return output


def _aggregate_diagnostics(paired: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    output = {}
    for metric in FOCUS_METRICS:
        values = [float(row[f"{metric}_diff"]) for row in paired]
        output[metric] = {
            "mean_ga_minus_heuristic": _mean(values),
            "num_events_ga_better": sum(1 for value in values if _is_better(metric, value)),
            "num_events_ga_worse": sum(1 for value in values if _is_worse(metric, value)),
            "num_events_equal": sum(1 for value in values if value == 0),
        }
    return output


def _ga_value_score(row: dict[str, Any]) -> float:
    return (
        float(row["initial_entity_coverage_diff"])
        + float(row["initial_source_coverage_diff"])
        + float(row["final_entity_coverage_diff"])
        + float(row["final_source_coverage_diff"])
        - float(row["num_repair_rounds_diff"])
        - 0.1 * float(row["num_repair_queries_diff"])
        - 0.001 * float(row["total_api_calls_diff"])
    )


def _is_better(metric: str, diff: float) -> bool:
    if metric in {"initial_need_query_repair", "num_repair_rounds", "num_repair_queries", "total_api_calls", "probe_api_calls"}:
        return diff < 0
    return diff > 0


def _is_worse(metric: str, diff: float) -> bool:
    if metric in {"initial_need_query_repair", "num_repair_rounds", "num_repair_queries", "total_api_calls", "probe_api_calls"}:
        return diff > 0
    return diff < 0


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any], helps: list[dict[str, Any]], hurts: list[dict[str, Any]]) -> None:
    lines = [
        "# Query Planner Ablation Analysis",
        "",
        f"- Events: {result['num_events']}",
        "",
        "## Aggregate Diagnostics",
        "",
    ]
    for metric, stats in result["aggregate_diagnostics"].items():
        lines.append(
            f"- `{metric}`: mean GA-heuristic={stats['mean_ga_minus_heuristic']:.4f}, "
            f"better={stats['num_events_ga_better']}, worse={stats['num_events_ga_worse']}, equal={stats['num_events_equal']}"
        )
    lines.extend(["", "## GA Helps Most", ""])
    lines.extend(_rank_lines(helps))
    lines.extend(["", "## GA Hurts Most", ""])
    lines.extend(_rank_lines(hurts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rank_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [f"- `{row['event_id']}`: ga_value_score={float(row['ga_value_score']):.4f}" for row in rows]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _float(value: str) -> float:
    if value in {"", "False", "false"}:
        return 0.0
    if value in {"True", "true"}:
        return 1.0
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
