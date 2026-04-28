"""Unified evaluation entrypoint."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from episoa.evaluation.faithfulness_metrics import evaluate_faithfulness_metrics
from episoa.evaluation.path_metrics import evaluate_path_metrics
from episoa.evaluation.retrieval_metrics import evaluate_retrieval_metrics
from episoa.evaluation.tuple_metrics import evaluate_tuple_metrics, load_jsonl, write_metrics_json


def evaluate(
    predictions_path: str | Path,
    gold_tuples_path: str | Path,
    gold_event_chains_path: str | Path,
    *,
    metrics_path: str | Path | None = None,
    summary_table_path: str | Path | None = None,
) -> dict[str, float]:
    """Evaluate predictions against gold tuples and gold event chains."""
    predictions = load_jsonl(predictions_path)
    gold_tuples = load_jsonl(gold_tuples_path)
    gold_event_chains = load_jsonl(gold_event_chains_path)

    metrics: dict[str, float] = {}
    metrics.update(evaluate_tuple_metrics(predictions, gold_tuples))
    metrics.update(evaluate_retrieval_metrics(predictions, gold_tuples))
    metrics.update(evaluate_path_metrics(predictions, gold_event_chains))
    metrics.update(evaluate_faithfulness_metrics(predictions, gold_tuples))

    if metrics_path is not None:
        write_metrics_json(metrics, metrics_path)
    if summary_table_path is not None:
        write_summary_table({"predictions": metrics}, summary_table_path)

    return metrics


def write_summary_table(rows_by_name: dict[str, dict[str, float]], output_path: str | Path) -> None:
    """Write a CSV summary table for one or more metric rows."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["name"]
    for metrics in rows_by_name.values():
        for key in metrics:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for name, metrics in rows_by_name.items():
            writer.writerow({"name": name, **metrics})


def evaluate_to_files(
    predictions_path: str | Path,
    gold_tuples_path: str | Path,
    gold_event_chains_path: str | Path,
    output_dir: str | Path,
) -> dict[str, float]:
    """Evaluate and write `metrics.json` plus `summary_table.csv` under output_dir."""
    output_path = Path(output_dir)
    metrics_path = output_path / "metrics.json"
    summary_table_path = output_path / "summary_table.csv"
    return evaluate(
        predictions_path,
        gold_tuples_path,
        gold_event_chains_path,
        metrics_path=metrics_path,
        summary_table_path=summary_table_path,
    )
