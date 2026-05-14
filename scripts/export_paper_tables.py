"""Export paper tables from benchmark evaluation results.

Generates:
- Table 1: Dataset statistics
- Table 2: Source type distribution
- Table 3: Benchmark task statistics
- Table 4: Main results (multi-method comparison)
- Table 5: Ablation results
- Table 6: Evidence support per-class results
- Table 7: Chain construction results
- Table 8: Error analysis summary

Output formats: CSV (for Excel/Google Sheets) and LaTeX (for paper).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def _write_latex(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def table_dataset_statistics(events_path: str, evidence_path: str, tuples_path: str, chains_path: str) -> list[list[str]]:
    events = _read_jsonl(Path(events_path))
    evidence = _read_jsonl(Path(evidence_path))
    tuples = _read_jsonl(Path(tuples_path))
    chains = _read_jsonl(Path(chains_path))

    domains = Counter(e.get("domain", "?") for e in events)
    source_types = Counter(ev.get("source_type", "?") for ev in evidence)

    rows = [
        ["Statistic", "Value"],
        ["Number of events", str(len(events))],
        ["Number of evidence records", str(len(evidence))],
        ["Number of gold tuples", str(len(tuples))],
        ["Number of gold event chains", str(len(chains))],
    ]
    for domain, count in sorted(domains.items()):
        rows.append([f"  Domain: {domain}", str(count)])
    rows.append(["Avg evidence per event", f"{len(evidence) / len(events):.1f}" if events else "0"])
    rows.append(["Avg tuples per event", f"{len(tuples) / len(events):.1f}" if events else "0"])
    rows.append(["Avg chains per event", f"{len(chains) / len(events):.1f}" if events else "0"])
    for st, count in sorted(source_types.items()):
        rows.append([f"  Source type: {st}", str(count)])
    return rows


def table_benchmark_statistics(benchmark_dir: str) -> list[list[str]]:
    stats = json.loads(Path(benchmark_dir, "benchmark_statistics.json").read_text(encoding="utf-8"))

    rows = [["Benchmark Task", "Rows", "Train", "Dev", "Test"]]
    for task in ["tuple_identification", "evidence_support_classification", "chain_construction"]:
        sc = stats.get("split_row_counts", {}).get(task, {})
        rows.append([
            task,
            str(stats.get("task_counts", {}).get(task, "")),
            str(sc.get("train", "")),
            str(sc.get("dev", "")),
            str(sc.get("test", "")),
        ])

    rows.append([])
    rows.append(["Label", "Count"])
    for label, count in stats.get("evidence_support_label_distribution", {}).items():
        rows.append([f"  {label}", str(count)])

    rows.append([])
    rows.append(["Split", "Events"])
    for split_name in ["train", "dev", "test"]:
        events_list = stats.get("splits", {}).get(split_name, [])
        rows.append([split_name, str(len(events_list))])
    return rows


def table_main_results(run_dirs: list[str]) -> list[list[str]]:
    """Compare multiple methods across benchmark tasks with all metrics."""
    headers = ["Method", "Tuple-F1(exact)", "Tuple-F1(LLM-judge)", "Tuple-F1(soft)",
               "EvSupport-Acc", "EvSupport-Sup-F1", "EvSupport-NEI-F1",
               "Chain-Ev-F1", "Chain-Ev-Recall", "Chain-Events-Matched"]
    rows = [headers]

    for run_dir in run_dirs:
        metrics_path = Path(run_dir, "metrics.json")
        if not metrics_path.exists():
            continue
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        method = Path(run_dir).name

        ti = metrics.get("tuple_identification", {})
        esc = metrics.get("evidence_support_classification", {})
        cc = metrics.get("chain_construction", {})

        rows.append([
            method,
            f"{ti.get('stakeholder_opinion_f1', 0):.4f}",
            f"{ti.get('stakeholder_opinion_f1_llm_judge', 0):.4f}",
            f"{ti.get('stakeholder_opinion_f1_soft', 0):.4f}",
            f"{esc.get('accuracy', 0):.4f}",
            f"{esc.get('per_class', {}).get('supported', {}).get('f1', 0):.4f}",
            f"{esc.get('per_class', {}).get('not_enough_info', {}).get('f1', 0):.4f}",
            f"{cc.get('evidence_f1', 0):.4f}",
            f"{cc.get('evidence_recall', 0):.4f}",
            f"{cc.get('events_with_chain_match', 0)}/{cc.get('events', 0)}",
        ])
    return rows


def table_ablation_results(ablation_dirs: list[str]) -> list[list[str]]:
    headers = ["Ablation", "Tuple-F1", "EvSupport-Acc", "Chain-Ev-F1"]
    rows = [headers]

    for name, run_dir in ablation_dirs:
        metrics_path = Path(run_dir, "metrics.json")
        if not metrics_path.exists():
            rows.append([name, "N/A", "N/A", "N/A"])
            continue
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        ti = metrics.get("tuple_identification", {})
        esc = metrics.get("evidence_support_classification", {})
        cc = metrics.get("chain_construction", {})

        rows.append([
            name,
            f"{ti.get('stakeholder_opinion_f1', 0):.4f}",
            f"{esc.get('accuracy', 0):.4f}",
            f"{cc.get('evidence_f1', 0):.4f}",
        ])
    return rows


def table_evidence_support_detail(run_dir: str) -> list[list[str]]:
    metrics_path = Path(run_dir, "metrics.json")
    if not metrics_path.exists():
        return [["No metrics found"]]

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    esc = metrics.get("evidence_support_classification", {})
    per_class = esc.get("per_class", {})

    rows = [["Class", "Precision", "Recall", "F1"]]
    for label in ["supported", "partially_supported", "not_enough_info"]:
        pc = per_class.get(label, {})
        rows.append([
            label,
            f"{pc.get('precision', 0):.4f}",
            f"{pc.get('recall', 0):.4f}",
            f"{pc.get('f1', 0):.4f}",
        ])
    rows.append(["Overall Accuracy", f"{esc.get('accuracy', 0):.4f}", "", ""])
    return rows


def table_chain_detail(run_dir: str) -> list[list[str]]:
    metrics_path = Path(run_dir, "metrics.json")
    if not metrics_path.exists():
        return [["No metrics found"]]

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    cc = metrics.get("chain_construction", {})

    return [
        ["Metric", "Value"],
        ["Events with chain match", str(cc.get("events_with_chain_match", 0))],
        ["Total events", str(cc.get("events", 0))],
        ["Evidence precision", f"{cc.get('evidence_precision', 0):.4f}"],
        ["Evidence recall", f"{cc.get('evidence_recall', 0):.4f}"],
        ["Evidence F1", f"{cc.get('evidence_f1', 0):.4f}"],
        ["Gold chains", str(cc.get("gold_chains", 0))],
        ["Pred chains", str(cc.get("pred_chains", 0))],
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export paper tables")
    parser.add_argument("--output-dir", default="outputs/paper_tables")
    parser.add_argument("--benchmark-dir", default="data/benchmark/pubevent_soa_lite_v3_repaired_plus_low37_gold")
    parser.add_argument("--events", default="data/pubevent_soa_lite/events.jsonl")
    parser.add_argument("--evidence", default="data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
    parser.add_argument("--tuples", default="data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_tuples.jsonl")
    parser.add_argument("--chains", default="data/pubevent_soa_lite/annotation_full_v3_repaired_plus_low37/llm_gold_event_chains.jsonl")
    parser.add_argument("--run-dirs", default="", help="Comma-separated run dirs for Table 4 comparison")
    parser.add_argument("--ablation-dirs", default="", help="Comma-separated 'name:path' pairs for Table 5")
    parser.add_argument("--format", choices=["csv", "latex", "both"], default="csv")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Table 1: Dataset statistics
    t1 = table_dataset_statistics(args.events, args.evidence, args.tuples, args.chains)
    _write_csv(output_dir / "table1_dataset_statistics.csv", t1)

    # Table 3: Benchmark task statistics
    t3 = table_benchmark_statistics(args.benchmark_dir)
    _write_csv(output_dir / "table3_benchmark_statistics.csv", t3)

    # Table 4: Main results comparison
    if args.run_dirs:
        run_dirs = [d.strip() for d in args.run_dirs.split(",") if d.strip()]
        t4 = table_main_results(run_dirs)
        _write_csv(output_dir / "table4_main_results.csv", t4)

    # Table 5: Ablation results
    if args.ablation_dirs:
        pairs = []
        for item in args.ablation_dirs.split(","):
            item = item.strip()
            if ":" in item:
                name, path = item.split(":", 1)
                pairs.append((name.strip(), path.strip()))
        t5 = table_ablation_results(pairs)
        _write_csv(output_dir / "table5_ablation_results.csv", t5)

    print(f"Tables exported to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
