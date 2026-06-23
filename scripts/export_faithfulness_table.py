"""Export the faithfulness / auditability table from current run artifacts.

Reframes the contribution: full_soe's value is not raw F1 (where it trails
direct_llm and verifier-free configs) but evidence-groundedness and field-level
faithfulness — ESR=1.0, UTR=0.0, zero over-inference, zero contradiction.

Source: ``outputs/runs_human_gold_v2/ablation_*/metrics.json`` +
``verifier_diagnostics_all.jsonl``. Does NOT use the pre-remediation
``verifier_rejection_analysis.json`` (247->58, stale).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "outputs" / "runs_human_gold_v2"
OUT_DIR = ROOT / "outputs" / "paper_tables"

ORDER = [
    "full_soe",
    "without_decomposed_verifier",
    "direct_llm",
    "without_soe_graph",
    "bm25_selector",
    "random_selector",
]


def _metrics(setting: str, runs_dir: Path) -> dict | None:
    path = runs_dir / f"ablation_{setting}" / "metrics.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _diagnosis_stats(setting: str, runs_dir: Path) -> dict:
    path = runs_dir / f"ablation_{setting}" / "verifier_diagnostics_all.jsonl"
    labels: Counter[str] = Counter()
    over_inference = 0
    contradiction = 0
    n = 0
    if not path.exists():
        return {"supported": "", "partially": "", "insufficient": "", "over_inference": "", "contradiction": "", "diagnosed": 0}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        n += 1
        labels[str(d.get("support_label", ""))] += 1
        vd = d.get("verification_diagnosis") or {}
        if isinstance(vd, dict):
            if vd.get("over_inference") is True:
                over_inference += 1
            if vd.get("contradiction_detected") is True:
                contradiction += 1
    return {
        "supported": labels.get("supported", 0),
        "partially": labels.get("partially_supported", 0),
        "insufficient": labels.get("insufficient_evidence", 0),
        "over_inference": over_inference,
        "contradiction": contradiction,
        "diagnosed": n,
    }


def export(runs_dir: Path) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "table_faithfulness_auditability.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Setting",
                "F1@0.3",
                "Num-Tuples",
                "Num-Tuples-All",
                "ESR",
                "UTR",
                "supported",
                "partially_supported",
                "insufficient_evidence",
                "over_inference",
                "contradiction_detected",
            ]
        )
        for setting in ORDER:
            m = _metrics(setting, runs_dir)
            if m is None:
                writer.writerow([setting, "MISSING"])
                continue
            stats = _diagnosis_stats(setting, runs_dir)
            writer.writerow(
                [
                    setting,
                    f"{m.get('Tuple-F1-semantic@0.3', 0):.4f}",
                    m.get("Num-Tuples", ""),
                    m.get("Num-Tuples-All", ""),
                    f"{m.get('ESR', 0):.3f}" if isinstance(m.get("ESR"), (int, float)) else "",
                    f"{m.get('UTR', 0):.3f}" if isinstance(m.get("UTR"), (int, float)) else "",
                    stats["supported"],
                    stats["partially"],
                    stats["insufficient"],
                    stats["over_inference"],
                    stats["contradiction"],
                ]
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    args = parser.parse_args()
    out = export(Path(args.runs_dir))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
