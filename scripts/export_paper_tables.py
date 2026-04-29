"""Export paper-ready CSV tables from EpiSOA run metrics."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from episoa.evaluation.metrics import ensure_paper_metric_keys


PAPER_COLUMNS = ["Method", "Tuple-F1", "Stake-F1", "Opinion-F1", "Sent-MacroF1", "ESR", "UTR", "Path-Recall@5"]
METRIC_TO_COLUMN = {
    "tuple_f1": "Tuple-F1",
    "stakeholder_f1": "Stake-F1",
    "opinion_f1": "Opinion-F1",
    "sentiment_macro_f1": "Sent-MacroF1",
    "evidence_support_rate": "ESR",
    "unsupported_tuple_rate": "UTR",
    "path_recall_at_k": "Path-Recall@5",
}
METHOD_LABELS = {
    "direct_llm": "Direct LLM",
    "few_shot_llm": "Few-shot LLM",
    "vanilla_rag": "Vanilla RAG",
    "graph_rag_style": "GraphRAG-style",
    "event_only_retrieval": "Event-only",
    "agent_only_collection": "Agent-only",
    "episoa_full": "EpiSOA",
    "without_fsm": "w/o C-FSM",
    "without_feedback_transition": "w/o feedback transition",
    "without_diversity": "w/o diversity objective",
    "without_graph": "w/o evidence graph",
    "without_event_chain": "w/o event-chain retriever",
    "without_verifier": "w/o verifier",
    "without_temporal_edges": "w/o temporal edges",
    "without_stakeholder_constraint": "w/o stakeholder constraint",
}


def export_paper_tables(runs_dir: str | Path, output: str | Path) -> dict[str, Path]:
    runs_path = Path(runs_dir)
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    main_rows: list[dict[str, Any]] = []
    ablation_rows: list[dict[str, Any]] = []

    for run_dir in sorted(path for path in runs_path.iterdir() if path.is_dir()):
        main_metrics = run_dir / "metrics.json"
        if main_metrics.exists() and (run_dir / "summary.json").exists():
            main_rows.append(_paper_row("episoa_full", main_metrics, include_path=False))

        if (run_dir / "baselines").exists():
            for metrics_path in sorted((run_dir / "baselines").glob("*/metrics.json")):
                main_rows.append(_paper_row(metrics_path.parent.name, metrics_path, include_path=False))

        if (run_dir / "ablations").exists():
            for metrics_path in sorted((run_dir / "ablations").glob("*/metrics.json")):
                ablation_rows.append(_paper_row(metrics_path.parent.name, metrics_path, include_path=True))

    paths = {
        "main_results": output_path / "main_results.csv",
        "ablation_results": output_path / "ablation_results.csv",
        "case_studies": output_path / "case_studies.jsonl",
    }
    _write_table(paths["main_results"], PAPER_COLUMNS[:-1], _dedupe_by_method(main_rows, include_path=False))
    _write_table(paths["ablation_results"], PAPER_COLUMNS, _dedupe_by_method(ablation_rows, include_path=True))
    _write_case_studies_jsonl(paths["case_studies"], _case_study_rows(runs_path))
    return paths


def _paper_row(method: str, metrics_path: Path, *, include_path: bool) -> dict[str, Any]:
    metrics = ensure_paper_metric_keys(json.loads(metrics_path.read_text(encoding="utf-8")))
    row = {"Method": METHOD_LABELS.get(method, method)}
    for metric_key, column in METRIC_TO_COLUMN.items():
        if column == "Path-Recall@5" and not include_path:
            continue
        row[column] = metrics[metric_key]
    return row


def _dedupe_by_method(rows: list[dict[str, Any]], *, include_path: bool) -> list[dict[str, Any]]:
    by_method: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_method[row["Method"]] = row
    preferred = PAPER_COLUMNS if include_path else PAPER_COLUMNS[:-1]
    return [{column: row.get(column, 0.0 if column != "Method" else "") for column in preferred} for row in by_method.values()]


def _write_table(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _case_study_rows(runs_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_path.iterdir() if path.is_dir()):
        case_path = run_dir / "case_study_examples.json"
        if not case_path.exists():
            continue
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        for case in payload.get("cases", []):
            rows.append(
                {
                    "run_id": run_dir.name,
                    "case_id": case.get("case_id", ""),
                    "case_type": case.get("case_type", ""),
                    "source": case.get("source", ""),
                }
            )
    return rows


def _write_case_studies_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export EpiSOA paper result tables.")
    parser.add_argument("--runs-dir", "--runs_dir", dest="runs_dir", default="outputs/runs")
    parser.add_argument("--output", default="outputs/paper_tables")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    paths = export_paper_tables(args.runs_dir, args.output)
    for name, path in paths.items():
        print(f"{name}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
