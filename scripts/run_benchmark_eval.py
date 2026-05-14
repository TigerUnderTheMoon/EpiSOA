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
    parser.add_argument("--benchmark-dir", default="data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: outputs/benchmark_runs/<run_id>)")
    parser.add_argument("--tasks", default="tuple_identification,evidence_support_classification,chain_construction",
                        help="Comma-separated task names; 'all' for all three")
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit task rows per type (0 = all)")
    parser.add_argument("--model-name", default=None, help="Override model name")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without calling LLM")
    parser.add_argument("--resume", action="store_true", help="Skip already-processed task_ids in existing predictions")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    model_name = args.model_name or cfg.model.get("model_name") or cfg.model.get("llm_model", "deepseek-v4-flash")

    benchmark_dir = Path(args.benchmark_dir)
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"outputs/benchmark_runs/{cfg.run_id}_{model_name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.tasks == "all":
        task_names = list(TASK_CONFIG)
    else:
        task_names = [t.strip() for t in args.tasks.split(",")]

    all_metrics: dict[str, dict] = {}

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
            existing_predictions = read_jsonl(pred_file)
            completed_ids = {p["task_id"] for p in existing_predictions if "task_id" in p}
            print(f"  Resume: {len(completed_ids)} already completed, {len(rows)} total rows")

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
                new_preds, _ = tc["runner"](client, [row], model_name)
                predictions.extend(new_preds)
                if (i + 1) % 5 == 0 or i == len(pending_rows) - 1:
                    write_jsonl(pred_file, predictions)
                    print(f"    [{i+1}/{len(pending_rows)}] saved")
            elapsed = time.time() - t0
            print(f"  Completed in {elapsed:.0f}s ({elapsed/len(pending_rows):.1f}s per row)")
        print(f"  Saved {len(predictions)} predictions to {pred_file}")

        # Recompute metrics from full prediction set
        _, metrics = tc["runner"](None, [], model_name)  # won't work — need direct metric call
        metrics = _recompute_metrics(task_name, predictions)

        metrics["model_name"] = model_name
        metrics["rows_processed"] = len(predictions)
        all_metrics[task_name] = metrics

        for k, v in metrics.items():
            print(f"  {k}: {v}")

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


if __name__ == "__main__":
    raise SystemExit(main())
