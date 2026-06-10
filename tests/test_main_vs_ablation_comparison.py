import csv
import json
from pathlib import Path

from scripts.build_main_vs_ablation_comparison import build_comparison


def test_comparison_marks_non_oracle_variant_matching_main_as_failed(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_metrics(main_dir / "metrics.json", f1_025=0.76, f1_03=0.75, f1_05=0.72)
    write_setting(runs_dir, "full_soe", f1_025=0.76, f1_03=0.75, f1_05=0.72)
    write_setting(runs_dir, "direct_llm", f1_025=0.74, f1_03=0.75, f1_05=0.70)
    write_setting(runs_dir, "oracle_evidence", f1_025=0.82, f1_03=0.80, f1_05=0.78)
    write_summary(runs_dir, ["full_soe", "direct_llm", "oracle_evidence"])

    result = build_comparison(runs_dir=runs_dir, main_dir=main_dir)

    assert result["status"] == "failed"
    assert result["generation_status"] == "passed"
    assert result["failures"][0]["setting"] == "direct_llm"
    assert result["failures"][0]["metric"] == "Tuple-F1-semantic@0.3"
    rows = read_rows(runs_dir / "main_vs_ablation_comparison.csv")
    direct = next(row for row in rows if row["setting"] == "direct_llm")
    oracle = next(row for row in rows if row["setting"] == "oracle_evidence")
    full = next(row for row in rows if row["setting"] == "full_soe")
    assert direct["verdict"] == "fail_ge_main_at_0.3"
    assert oracle["comparison_included"] == "false"
    assert oracle["verdict"] == "upper_bound_only"
    assert full["comparison_included"] == "false"
    assert full["verdict"] == "not_applicable_full_soe_sanity"


def test_comparison_passes_when_non_oracle_variants_are_strictly_below_main(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    main_dir = runs_dir / "main"
    main_dir.mkdir(parents=True)
    write_metrics(main_dir / "metrics.json", f1_025=0.76, f1_03=0.75, f1_05=0.72)
    write_setting(runs_dir, "full_soe", f1_025=0.76, f1_03=0.75, f1_05=0.72)
    write_setting(runs_dir, "direct_llm", f1_025=0.74, f1_03=0.73, f1_05=0.70)
    write_summary(runs_dir, ["full_soe", "direct_llm"])

    result = build_comparison(runs_dir=runs_dir, main_dir=main_dir)

    assert result["status"] == "passed"
    assert result["generation_status"] == "passed"
    rows = read_rows(runs_dir / "main_vs_ablation_comparison.csv")
    direct = next(row for row in rows if row["setting"] == "direct_llm")
    assert direct["verdict"] == "pass_below_main_all_thresholds"


def write_setting(
    runs_dir: Path,
    setting: str,
    *,
    f1_025: float,
    f1_03: float,
    f1_05: float,
) -> None:
    setting_dir = runs_dir / f"ablation_{setting}"
    setting_dir.mkdir(parents=True)
    write_metrics(setting_dir / "metrics.json", f1_025=f1_025, f1_03=f1_03, f1_05=f1_05)


def write_metrics(path: Path, *, f1_025: float, f1_03: float, f1_05: float) -> None:
    payload = {
        "Metric-Scope": "gold_event_scope",
        "Num-Gold": 10,
        "Num-Tuples": 9,
        "Num-Tuples-All": 9,
        "Tuple-F1-soft": 0.4,
        "Tuple-Precision": 0.5,
        "Tuple-Recall": 0.6,
        "Tuple-F1-semantic@0.25": f1_025,
        "Tuple-Precision-semantic@0.25": f1_025,
        "Tuple-Recall-semantic@0.25": f1_025,
        "Tuple-F1-semantic@0.3": f1_03,
        "Tuple-Precision-semantic@0.3": f1_03,
        "Tuple-Recall-semantic@0.3": f1_03,
        "Tuple-F1-semantic@0.5": f1_05,
        "Tuple-Precision-semantic@0.5": f1_05,
        "Tuple-Recall-semantic@0.5": f1_05,
        "Stakeholder-Recall": 0.3,
        "Opinion-Recall": 0.2,
        "ESR": 0.9,
        "UTR": 0.1,
        "Excluded-Predictions": 0,
        "Excluded-Event-Count": 0,
        "Excluded-Event-Ids": "",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary(runs_dir: Path, settings: list[str]) -> None:
    (runs_dir / "ablation_summary.json").write_text(
        json.dumps({"status": "completed", "settings": settings}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
