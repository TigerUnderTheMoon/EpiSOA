"""Write event-level ablation delta CSVs and the ablation audit report."""

from __future__ import annotations

import argparse

from episoa.config import load_config
from episoa.data.loader import read_typed_jsonl
from episoa.data.schema import GoldTuple
from episoa.evaluation.ablation_audit import (
    CHAIN_ABLATION_SETTINGS,
    write_ablation_audit_report,
    write_ablation_delta_audits,
)
from episoa.pipeline import ABLATION_SETTINGS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit EpiSOA ablation deltas")
    parser.add_argument("--config", default="configs/ablation.yaml")
    parser.add_argument("--runs-dir", default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    runs_dir = args.runs_dir or config.output.get("runs_dir", "outputs/runs")
    settings = list(config.ablation.get("settings", list(ABLATION_SETTINGS)))
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)

    delta_paths = write_ablation_delta_audits(
        runs_dir=runs_dir,
        gold_tuples=gold,
        settings=[setting for setting in CHAIN_ABLATION_SETTINGS if setting in settings],
    )
    report_path = write_ablation_audit_report(
        runs_dir=runs_dir,
        settings=settings,
        flags_by_setting={setting: ABLATION_SETTINGS.get(setting, {}) for setting in settings},
    )

    for setting, path in delta_paths.items():
        print(f"{setting}: {path}")
    print(f"audit_report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
