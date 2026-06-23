"""Export Table 5 (main results) and Table 6 (ablation) as CSV from the single
canonical source: ``outputs/runs_human_gold_v2/ablation_*/metrics.json``.

This script exists so the supporting-data package CSVs are generated from the
same source the manuscript renderer uses, eliminating the stale-number
regression where ``main_vs_ablation_comparison.csv`` (44 tuples / F1=0.1468)
leaked into the docx while the abstract used current numbers (82 / 0.3906).

Read-only: emits CSVs under ``outputs/paper_tables/``. Does NOT read
``main_vs_ablation_comparison.csv`` or the legacy main run dir.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "outputs" / "runs_human_gold_v2"
OUT_DIR = ROOT / "outputs" / "paper_tables"

# Table 6 row order (oracle_evidence intentionally excluded: selector-mode bug
# produced 0 tuples, not a real upper bound). direct_llm retained as a weak,
# evidence-unaligned baseline.
TABLE6_ORDER = [
    "full_soe",
    "without_soe_graph",
    "without_decomposed_verifier",
    "full_soe_high_recall",
    "without_chain_aware_selection",
    "quality_topk_selector",
    "random_selector",
    "bm25_selector",
    "direct_llm",
]

TABLE5_ROWS = [
    "Num-Gold",
    "Num-Tuples",
    "Tuple-F1-semantic",
    "Tuple-Precision-semantic",
    "Tuple-Recall-semantic",
    "Tuple-F1-semantic@0.25",
    "Tuple-F1-semantic@0.3",
    "Tuple-F1-semantic@0.5",
    "Tuple-F1-char@0.5",
    "Tuple-F1-exact",
    "Sentiment-Acc",
    "ESR",
    "UTR",
]


def _load_metrics(setting: str) -> dict | None:
    path = RUNS_DIR / f"ablation_{setting}" / "metrics.json"
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.4f}" if isinstance(value, float) else str(value)
    return "" if value is None else str(value)


def export_table5() -> Path:
    metrics = _load_metrics("full_soe")
    if metrics is None:
        raise FileNotFoundError("ablation_full_soe/metrics.json not found")
    out = OUT_DIR / "table5_main_results_current.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["指标", "数值"])
        for key in TABLE5_ROWS:
            writer.writerow([key, _fmt(metrics.get(key))])
    return out


def export_table6() -> Path:
    out = OUT_DIR / "table6_ablation_results_current.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Setting", "F1@0.5", "F1@0.3", "F1@0.25", "Soft(char@0.5)", "Num-Tuples"])
        for setting in TABLE6_ORDER:
            metrics = _load_metrics(setting)
            if metrics is None:
                writer.writerow([setting, "", "", "", "", "MISSING"])
                continue
            writer.writerow(
                [
                    setting,
                    _fmt(metrics.get("Tuple-F1-semantic@0.5")),
                    _fmt(metrics.get("Tuple-F1-semantic@0.3")),
                    _fmt(metrics.get("Tuple-F1-semantic@0.25")),
                    _fmt(metrics.get("Tuple-F1-soft", metrics.get("Tuple-F1-char@0.5"))),
                    _fmt(metrics.get("Num-Tuples")),
                ]
            )
    return out


def main() -> int:
    global RUNS_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    args = parser.parse_args()
    RUNS_DIR = Path(args.runs_dir)
    t5 = export_table5()
    t6 = export_table6()
    print(f"wrote {t5}")
    print(f"wrote {t6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
