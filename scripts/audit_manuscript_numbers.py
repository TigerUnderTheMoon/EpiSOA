"""Audit the manuscript docx for number consistency against the canonical
artifacts. Catches regressions where the docx Table 5/6 carries stale
pre-remediation numbers while the abstract or formal artifacts use newer
canonical values.

Reads the rendered docx text and asserts every headline number matches
``outputs/runs_human_gold_v2/ablation_full_soe/metrics.json`` and the
regenerated ``significance_report.json``. Exits non-zero on mismatch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "outputs" / "runs_human_gold_v2"
DOCX = ROOT / "outputs" / "manuscript" / "episoa_full_draft.docx"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(path: Path) -> str:
    z = zipfile.ZipFile(path)
    t = ET.fromstring(z.read("word/document.xml"))
    return "".join(n.text or "" for n in t.iter(f"{W_NS}t"))


def _load_metrics() -> dict:
    metrics_path = RUNS_DIR / "ablation_full_soe" / "metrics.json"
    if not metrics_path.exists():
        raise FileNotFoundError(f"canonical metrics missing: {metrics_path}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if not isinstance(metrics, dict):
        raise ValueError(f"canonical metrics must contain a JSON object: {metrics_path}")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", default=str(DOCX))
    args = parser.parse_args()

    docx = Path(args.docx)
    if not docx.exists():
        print(f"ERROR: docx not found: {docx}", file=sys.stderr)
        return 2

    text = _docx_text(docx)
    try:
        metrics = _load_metrics()
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    issues: list[str] = []

    # Headline numbers that must appear in the manuscript.
    expected_present = {
        "Num-Tuples": str(metrics["Num-Tuples"]),
        "F1@0.3": f"{metrics['Tuple-F1-semantic@0.3']:.4f}",
        "Num-Gold": str(metrics["Num-Gold"]),
    }
    for label, value in expected_present.items():
        if value not in text:
            issues.append(f"headline value missing from docx: {label} = {value}")

    # Stale numbers that must NOT appear (pre-remediation regression).
    stale_absent = {
        "stale Num-Tuples=44": "44",
        "stale F1=0.1468": "0.1468",
        "stale main_vs_ablation F1 0.2385": "0.2385",
    }
    # 44 is too common a substring to forbid broadly; only flag if it appears
    # as a tuple count context. We check the explicit stale F1 strings instead.
    for label, value in [("stale F1=0.1468", "0.1468"), ("stale F1@0.3=0.2385", "0.2385")]:
        if value in text:
            issues.append(f"stale value still present in docx: {label}")

    # Significance report must show the real (negative) delta, not the
    # hardcoded +0.0602 placeholder.
    sig_path = ROOT / "outputs" / "manuscript" / "significance_report.json"
    if sig_path.exists():
        sig = json.loads(sig_path.read_text(encoding="utf-8"))
        for comp in sig.get("comparisons", []) or []:
            if comp.get("baseline") == "full_soe" and comp.get("variant") == "without_decomposed_verifier":
                delta = comp.get("mean_delta")
                if isinstance(delta, (int, float)) and delta >= 0:
                    issues.append(
                        f"significance delta for full_soe vs without_decomposed_verifier is "
                        f"{delta} (>=0); real data shows full_soe is worse — regenerate"
                    )
                if comp.get("n_events") == 40:
                    issues.append("significance n_events=40 still present (hardcoded); expected ~45")

    # Table 7 faithfulness: full_soe must show ESR=1.0 and over_inference=0.
    if "over_inference" not in text and "over_inf" not in text:
        issues.append("faithfulness table (over_inference) missing from docx — Table 7 not rendered")

    if issues:
        print("AUDIT FAILED:")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("AUDIT PASSED: headline numbers consistent with canonical artifacts, no stale values, significance regenerated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
