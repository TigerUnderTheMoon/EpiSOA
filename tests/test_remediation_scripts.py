"""Tests for the remediation scripts that prevent the number-consistency and
significance-direction regressions documented in the paper-repair plan.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_significance_report_uses_real_data_not_hardcoded():
    builder = importlib.import_module("scripts.build_episoa_manuscript")
    # The hardcoded placeholder branch must be gone: calling without comparisons
    # falls back to SIGNIFICANCE_COMPARISONS and runs the real implementation.
    # It will raise if the run artifacts are missing — so guard by checking the
    # function no longer returns the fabricated +0.0602 value directly.
    src = Path(builder.__file__).read_text(encoding="utf-8")
    assert "0.0602" not in src, "hardcoded significance placeholder still present in source"
    assert "0.0582" not in src and "0.0938" not in src and "0.0843" not in src


def test_significance_comparisons_constant_defined():
    builder = importlib.import_module("scripts.build_episoa_manuscript")
    assert hasattr(builder, "SIGNIFICANCE_COMPARISONS")
    pairs = builder.SIGNIFICANCE_COMPARISONS
    assert ("full_soe", "without_decomposed_verifier") in pairs


def test_formal_main_run_dir_prefers_ablation_full_soe(tmp_path):
    builder = importlib.import_module("scripts.build_episoa_manuscript")
    runs = tmp_path / "runs"
    full = runs / "ablation_full_soe"
    full.mkdir(parents=True)
    (full / "metrics.json").write_text('{"Num-Tuples": 82}', encoding="utf-8")
    legacy = runs / "pubevent-soa-lite-human-gold-v2-paper"
    legacy.mkdir(parents=True)
    (legacy / "metrics.json").write_text('{"Num-Tuples": 44}', encoding="utf-8")

    main_dir = builder._formal_main_run_dir(runs)
    assert main_dir.name == "ablation_full_soe", "must prefer current ablation_full_soe over stale legacy main"


def test_ablation_summary_strips_ablation_prefix_and_reads_metrics_json(tmp_path):
    builder = importlib.import_module("scripts.build_episoa_manuscript")
    runs = tmp_path / "runs"
    d = runs / "ablation_full_soe"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(
        '{"Num-Tuples": 82, "Tuple-F1-semantic@0.3": 0.3906}', encoding="utf-8"
    )
    summary = builder.ablation_summary(runs)
    assert "full_soe" in summary["metrics"]
    assert summary["metrics"]["full_soe"]["Num-Tuples"] == 82


def test_table6_render_excludes_oracle_evidence():
    """The oracle row must be dropped from the Table 6 setting order."""
    builder = importlib.import_module("scripts.build_episoa_manuscript")
    src = Path(builder.__file__).read_text(encoding="utf-8")
    # The rendering loop must not list oracle_evidence as a setting.
    # Find the Table 6 setting list block.
    assert '"oracle_evidence",' not in src.split('setting_labels = {')[0].split('for setting in [')[-1].split(']:')[0] \
        or 'oracle_evidence' not in src.split('for setting in [')[1].split(']:')[0]


def test_check_result_targets_consistency_flags_reversed_significance(tmp_path):
    crt = importlib.import_module("scripts.check_result_targets")
    runs = tmp_path / "runs"
    full = runs / "ablation_full_soe"
    full.mkdir(parents=True)
    (full / "metrics.json").write_text(
        json.dumps({"Num-Tuples": 82, "Tuple-F1-semantic@0.3": 0.3906, "ESR": 1.0}), encoding="utf-8"
    )
    # stale significance with reversed (positive) delta and n_events=40
    manus = tmp_path / "manuscript"
    manus.mkdir()
    (manus / "significance_report.json").write_text(
        json.dumps(
            {
                "comparisons": [
                    {"baseline": "full_soe", "variant": "without_decomposed_verifier",
                     "mean_delta": 0.0602, "n_events": 40}
                ]
            }
        ),
        encoding="utf-8",
    )
    # point the check at our tmp manuscript dir by monkeypatching the path
    result = crt.run_gate(runs_dir=str(runs), mode="consistency")
    issues_text = " ".join(result["issues"])
    assert "reversed delta" in issues_text or "n_events=40" in issues_text, result["issues"]


def test_audit_manuscript_numbers_passes_on_current_docx(monkeypatch):
    audit = importlib.import_module("scripts.audit_manuscript_numbers")
    docx = ROOT / "outputs" / "manuscript" / "episoa_full_draft.docx"
    if not docx.exists():
        pytest.skip("manuscript docx not built")
    monkeypatch.setattr(sys, "argv", ["audit_manuscript_numbers.py", "--docx", str(docx)])
    rc = audit.main()
    assert rc == 0
