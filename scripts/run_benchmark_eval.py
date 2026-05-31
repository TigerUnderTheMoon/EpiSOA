"""Run LLM-based benchmark evaluation on EpiSOA benchmark tasks.

Supports: tuple_identification, evidence_support_classification, chain_construction.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from episoa.config import load_config
from episoa.data.loader import read_jsonl, write_jsonl
from episoa.evaluation.benchmark_runner import (
    run_tuple_identification,
    run_evidence_support,
    run_chain_construction,
)
from episoa.llm.client import build_llm_client


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

TASK_CONFIG = {
    "tuple_identification": {
        "file": "tuple_identification.jsonl",
        "runner": run_tuple_identification,
        "output_prefix": "tuple_identification",
    },
    "evidence_support_classification": {
        "file": "evidence_support_classification.jsonl",
        "runner": run_evidence_support,
        "output_prefix": "evidence_support",
    },
    "chain_construction": {
        "file": "chain_construction.jsonl",
        "runner": run_chain_construction,
        "output_prefix": "chain_construction",
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run benchmark evaluation with LLM")
    parser.add_argument("--config", default="configs/paper.yaml", help="YAML config with model settings")
    parser.add_argument("--benchmark-dir", default="data/benchmark/pubevent_soa_lite_human_gold_v2")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: outputs/benchmark_runs/<run_id>)")
    parser.add_argument("--tasks", default="tuple_identification,evidence_support_classification,chain_construction",
                        help="Comma-separated task names; 'all' for all three")
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit task rows per type (0 = all)")
    parser.add_argument("--model-name", default=None, help="Override model name")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without calling LLM")
    parser.add_argument("--resume", action="store_true", help="Skip already-processed task_ids in existing predictions")
    parser.add_argument("--prompt-dir", default="prompts", help="Directory with benchmark prompt .md files (default: prompts/)")
    parser.add_argument("--cost-per-sample", type=float, default=0.0, help="Optional externally estimated API cost per task row.")
    parser.add_argument("--human-effort-ratio", type=float, default=0.0, help="Optional human minutes / total minutes ratio for reporting.")
    parser.add_argument(
        "--allow-prediction-errors",
        action="store_true",
        help="Allow predictions containing _error to be included in metrics.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    model_name = args.model_name or cfg.model.get("model_name") or cfg.model.get("llm_model", "gpt-5.5")

    benchmark_dir = Path(args.benchmark_dir)
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"outputs/benchmark_runs/{cfg.run_id}_{model_name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.tasks == "all":
        task_names = list(TASK_CONFIG)
    else:
        task_names = [t.strip() for t in args.tasks.split(",")]

    all_metrics: dict[str, dict] = {}
    fatal_prediction_errors: list[dict[str, object]] = []

    if not args.dry_run:
        client = build_llm_client(cfg.model)
        print(f"Model: {model_name}")
        print(f"Base URL: {client.base_url}")
        print(f"Benchmark: {benchmark_dir}")
        print(f"Output: {output_dir}")
        print(f"Tasks: {task_names}")
        if args.resume:
            print(f"Resume: enabled")
        print()

    for task_name in task_names:
        tc = TASK_CONFIG[task_name]
        task_file = benchmark_dir / tc["file"]
        if not task_file.exists():
            print(f"[SKIP] {task_name}: {task_file} not found")
            continue

        pred_file = output_dir / f"{tc['output_prefix']}_predictions.jsonl"

        print(f"[{task_name}] Loading {task_file} ...")
        rows = read_jsonl(task_file)
        if args.max_tasks and args.max_tasks < len(rows):
            rows = rows[:args.max_tasks]

        # Resume: load existing predictions and skip completed task_ids
        existing_predictions = []
        completed_ids = set()
        if args.resume and pred_file.exists():
            loaded_predictions = read_jsonl(pred_file)
            error_predictions = _prediction_error_rows(loaded_predictions)
            existing_predictions = [
                pred for pred in loaded_predictions
                if not _prediction_error_message(pred)
            ]
            completed_ids = {p["task_id"] for p in existing_predictions if "task_id" in p}
            print(f"  Resume: {len(completed_ids)} already completed, {len(rows)} total rows")
            if error_predictions:
                print(f"  Resume: retrying {len(error_predictions)} prior error predictions")

        pending_rows = [r for r in rows if r["task_id"] not in completed_ids]

        if args.dry_run:
            print(f"  Would process {len(pending_rows)} rows (dry-run)")
            continue

        if not pending_rows:
            print(f"  All {len(rows)} rows already completed, computing metrics only")
            predictions = existing_predictions
        else:
            print(f"  Processing {len(pending_rows)}/{len(rows)} rows ...")
            t0 = time.time()
            predictions = existing_predictions[:]
            for i, row in enumerate(pending_rows):
                row_start = time.time()
                new_preds, _ = tc["runner"](client, [row], model_name, prompt_dir=args.prompt_dir)
                latency = time.time() - row_start
                for pred in new_preds:
                    pred.setdefault("runtime", {})
                    pred["runtime"]["latency_seconds"] = round(latency, 4)
                    pred["runtime"]["estimated_cost"] = args.cost_per_sample
                predictions.extend(new_preds)
                if (i + 1) % 5 == 0 or i == len(pending_rows) - 1:
                    write_jsonl(pred_file, predictions)
                    print(f"    [{i+1}/{len(pending_rows)}] saved")
            elapsed = time.time() - t0
            print(f"  Completed in {elapsed:.0f}s ({elapsed/len(pending_rows):.1f}s per row)")
        write_jsonl(pred_file, predictions)
        print(f"  Saved {len(predictions)} predictions to {pred_file}")

        # Recompute metrics from full prediction set
        # Recompute metrics from full prediction set (comment above left intentionally)
        metrics = _recompute_metrics(task_name, predictions)

        metrics["model_name"] = model_name
        metrics["rows_processed"] = len(predictions)
        metrics["latency"] = latency_summary(predictions)
        metrics["cost_per_sample"] = args.cost_per_sample
        metrics["estimated_total_cost"] = round(args.cost_per_sample * len(predictions), 6)
        metrics["human_effort_ratio"] = args.human_effort_ratio
        prediction_errors = _prediction_error_rows(predictions)
        metrics["prediction_error_count"] = len(prediction_errors)
        if prediction_errors:
            metrics["prediction_error_examples"] = _prediction_error_examples(prediction_errors)
        all_metrics[task_name] = metrics

        for k, v in metrics.items():
            print(f"  {k}: {v}")

        if prediction_errors and not args.allow_prediction_errors:
            fatal_prediction_errors.append(
                {
                    "task": task_name,
                    "prediction_error_count": len(prediction_errors),
                    "first_error": _prediction_error_message(prediction_errors[0]),
                }
            )
            break

    if not args.dry_run:
        metrics_file = output_dir / "metrics.json"
        # Merge with existing metrics if resuming
        old_metrics = {}
        if args.resume and metrics_file.exists():
            try:
                old_metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        old_metrics.update(all_metrics)
        metrics_file.write_text(json.dumps(old_metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nMetrics saved to {metrics_file}")

        config_snapshot = {
            "model_name": model_name,
            "benchmark_dir": str(benchmark_dir),
            "tasks": task_names,
            "config_file": args.config,
        }
        (output_dir / "config.yaml").write_text(yaml.dump(config_snapshot, allow_unicode=True), encoding="utf-8")

    if fatal_prediction_errors:
        print("\nPrediction errors detected; exiting nonzero instead of reporting them as valid zero metrics.")
        for item in fatal_prediction_errors:
            print(f"  {item['task']}: {item['prediction_error_count']} errors; first_error={item['first_error']}")
        return 1

    return 0


def _recompute_metrics(task_name: str, predictions: list[dict]) -> dict:
    """Recompute metrics from full prediction list."""
    from episoa.evaluation.benchmark_metrics import (
        eval_tuple_identification,
        eval_evidence_support,
        eval_chain_construction,
    )
    if task_name == "tuple_identification":
        return eval_tuple_identification(predictions)
    elif task_name == "evidence_support_classification":
        return eval_evidence_support(predictions)
    elif task_name == "chain_construction":
        return eval_chain_construction(predictions)
    return {"error": f"unknown task: {task_name}"}


def _prediction_error_message(prediction_row: dict) -> str:
    prediction = prediction_row.get("prediction")
    if isinstance(prediction, dict):
        return str(prediction.get("_error") or "")
    return ""


def _prediction_error_rows(predictions: list[dict]) -> list[dict]:
    return [pred for pred in predictions if _prediction_error_message(pred)]


def _prediction_error_examples(predictions: list[dict], limit: int = 3) -> list[dict[str, str]]:
    examples = []
    for pred in predictions[:limit]:
        examples.append(
            {
                "task_id": str(pred.get("task_id", "")),
                "error": _prediction_error_message(pred).splitlines()[0],
            }
        )
    return examples


def latency_summary(predictions: list[dict]) -> dict:
    values = sorted(
        float(pred.get("runtime", {}).get("latency_seconds", 0) or 0)
        for pred in predictions
        if pred.get("runtime", {}).get("latency_seconds") is not None
    )
    values = [value for value in values if value > 0]
    if not values:
        return {"p50_seconds": None, "p95_seconds": None, "mean_seconds": None}
    return {
        "p50_seconds": round(percentile(values, 0.50), 4),
        "p95_seconds": round(percentile(values, 0.95), 4),
        "mean_seconds": round(sum(values) / len(values), 4),
    }


def percentile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


if __name__ == "__main__":
    raise SystemExit(main())
