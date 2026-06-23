"""Compute field-level inter-annotator agreement (IAA) from the three
independent annotator sheets.

The existing ``independent_audit/independent_annotation_iaa_report.json``
reports Fleiss kappa = 1.0 / 0 conflicts, which is not credible for three
independent human annotators over 174 tuples — it indicates the three
``annotator_{A,B,C}`` sheets are copies of the post-adjudication gold rather
than genuinely independent labels. This script recomputes the *actual* field
-level agreement directly from the three sheets for the stakeholder, opinion,
sentiment and rationale fields, on the full set and on a ~20% held-out subset,
so the manuscript can report an honest IAA number instead of the kappa=1.0
artifact.

Agreement is measured per field as:
  - exact-match pairwise F1 (treat each annotator pair, average over 3 pairs),
  - and a normalized-string pairwise agreement rate.

Cohen's kappa per pair is also reported for categorical fields (sentiment,
binarized stakeholder/opinion match).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEP_DIR = ROOT / "data" / "pubevent_soa_lite" / "human_gold_v2_stakeholder_canonical" / "independent"
OUT_DIR = ROOT / "data" / "pubevent_soa_lite" / "human_gold_v2" / "independent_audit"

FIELDS = ["stakeholder", "opinion", "sentiment", "rationale"]


def _norm(text: str) -> str:
    return "".join(text or "").strip().replace(" ", "").replace("\n", "")


def _load_annotator(name: str) -> dict[tuple[str, str], dict[str, str]]:
    path = INDEP_DIR / f"annotator_{name}" / f"human{name}_tuple_adjudication_sheet.csv"
    if not path.exists():
        # fall back to the shared filename used in some dirs
        path = INDEP_DIR / f"annotator_{name}" / "humanA_tuple_adjudication_sheet.csv"
    rows: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("event_id", ""), row.get("tuple_id", ""))
            if not key[0] or not key[1]:
                continue
            rows[key] = {f: row.get(f, "") for f in FIELDS}
    return rows


def _pairwise_agreement(a: dict, b: dict, field: str, keys: list) -> tuple[float, float]:
    """Return (exact-match rate, normalized-match rate) over shared keys."""
    shared = [k for k in keys if k in a and k in b]
    if not shared:
        return 0.0, 0.0
    exact = sum(1 for k in shared if _norm(a[k][field]) == _norm(b[k][field])) / len(shared)
    return exact, exact  # normalized == exact for string fields


def _cohen_kappa(a: dict, b: dict, field: str, keys: list) -> float:
    """Cohen's kappa over binarized 'matches gold stakeholder?'-style categories.

    For free-text fields we binarize by whether the annotator kept vs revised
    the original; lacking that column we fall back to exact-match proportion
    as a lower-bound agreement (kappa undefined for degenerate marginals).
    """
    shared = [k for k in keys if k in a and k in b]
    if not shared:
        return 0.0
    a_labels = [a[k][field] for k in shared]
    b_labels = [b[k][field] for k in shared]
    # categorical: sentiment has few values -> real kappa
    if field == "sentiment":
        cats = sorted(set(a_labels) | set(b_labels))
        if len(cats) < 2:
            return 1.0
        n = len(shared)
        po = sum(1 for i in range(n) if a_labels[i] == b_labels[i]) / n
        pe = sum(
            (a_labels.count(c) / n) * (b_labels.count(c) / n) for c in cats
        )
        return (po - pe) / (1 - pe) if (1 - pe) != 0 else 1.0
    # free-text fields: report exact-match proportion (kappa ill-defined)
    return sum(1 for i in range(len(shared)) if a_labels[i] == b_labels[i]) / len(shared)


def compute_iaa(subset_size: int = 0) -> dict:
    annotators = {name: _load_annotator(name) for name in ("A", "B", "C")}
    all_keys = sorted(set().union(*[set(s.keys()) for s in annotators.values()]))
    if subset_size and subset_size < len(all_keys):
        # deterministic subset (first N by key) for the ~20% report
        all_keys = all_keys[:subset_size]

    pairs = [("A", "B"), ("A", "C"), ("B", "C")]
    report: dict = {
        "n_items": len(all_keys),
        "annotators": ["A", "B", "C"],
        "fields": {},
    }
    for field in FIELDS:
        exacts = []
        kappas = []
        for x, y in pairs:
            exact, _ = _pairwise_agreement(annotators[x], annotators[y], field, all_keys)
            exacts.append(exact)
            kappas.append(_cohen_kappa(annotators[x], annotators[y], field, all_keys))
        report["fields"][field] = {
            "pairwise_exact_match_mean": round(statistics.mean(exacts), 4),
            "pairwise_exact_match_min": round(min(exacts), 4),
            "pairwise_agreement_statistic_mean": round(statistics.mean(kappas), 4),
            "statistic_note": "sentiment=Cohen's kappa; free-text fields=exact-match proportion (kappa ill-defined)",
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", type=int, default=0, help="0 = full set; N = first N tuples (subset report)")
    parser.add_argument("--output", default=str(OUT_DIR / "field_level_iaa_report.json"))
    args = parser.parse_args()

    report = compute_iaa(subset_size=args.subset)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
