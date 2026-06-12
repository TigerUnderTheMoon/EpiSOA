"""Run ablation settings one at a time to avoid timeout issues.

Usage:
    python scripts/run_ablation_sequential.py [--config configs/ablation.yaml] [--force] [--settings full_soe,direct_llm,...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

from episoa.config import load_config
from episoa.data.schema import EventRecord, EvidenceRecord, GoldTuple, GoldEventChain
from episoa.data.loader import read_typed_jsonl
from episoa.pipeline import (
    ABLATION_SETTINGS,
    PIPELINE_FLAG_KEYS,
    _validate_pipeline_data,
    _create_llm_client,
    _get_git_commit,
    _run_core_pipeline,
    print_api_config_status,
)


def run_single_setting(config, setting_name, flags, runs_dir, config_path, force=False):
    """Run a single ablation setting."""
    setting_dir = runs_dir / f"ablation_{setting_name}"

    if force and setting_dir.exists():
        shutil.rmtree(setting_dir)
        print(f"  [FORCE] removed {setting_dir}")

    setting_dir.mkdir(parents=True, exist_ok=True)

    events = read_typed_jsonl(config.data["events_path"], EventRecord)
    evidence = read_typed_jsonl(config.data["evidence_path"], EvidenceRecord)
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)
    gold_chains = read_typed_jsonl(config.data["gold_event_chains_path"], GoldEventChain)

    llm_client = _create_llm_client(config)
    timestamp = datetime.now(timezone.utc).isoformat()
    git_commit = _get_git_commit()

    shutil.copyfile(config_path, setting_dir / "config_snapshot.yaml")

    pipeline_flags = {k: v for k, v in flags.items() if k in PIPELINE_FLAG_KEYS}

    max_evidence = config.ablation.get("max_evidence_per_event", 24)
    max_tuples = flags.get("max_tuples_per_event", config.ablation.get("max_tuples_per_event", 8))

    print(f"\n{'='*60}")
    print(f"  Running ablation: {setting_name}")
    print(f"  Flags: {json.dumps(pipeline_flags, ensure_ascii=False)}")
    print(f"  Max evidence: {max_evidence}, Max tuples: {max_tuples}")
    print(f"{'='*60}")

    summary = _run_core_pipeline(
        config=config,
        events=events,
        evidence=evidence,
        gold=gold,
        gold_chains=gold_chains,
        llm_client=llm_client,
        output_dir=setting_dir,
        run_id=f"ablation_{setting_name}",
        method_version=pipeline_flags.get("method_version", "soe_v3"),
        selector_mode=pipeline_flags.get("selector_mode", "coverage_optimized"),
        max_evidence_per_event=max_evidence,
        max_tuples_per_event=max_tuples,
        timestamp=timestamp,
        git_commit=git_commit,
        **{k: v for k, v in pipeline_flags.items()
           if k not in ("method_version", "selector_mode", "max_tuples_per_event", "max_evidence_per_event")},
    )

    print(f"\n  [{setting_name}] tuples={summary.get('num_tuples_generated', 0)} "
          f"failures={summary.get('num_api_failures', 0)}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run ablation settings sequentially")
    parser.add_argument("--config", default="configs/ablation.yaml")
    parser.add_argument("--force", action="store_true", help="Remove existing directories before running")
    parser.add_argument("--settings", default=None,
                        help="Comma-separated list of settings to run (default: all from config)")
    args = parser.parse_args()

    config = load_config(args.config)
    print_api_config_status(config)
    validation = _validate_pipeline_data(config)
    if not validation["paper_data_ready"]:
        print(f"ERROR: paper data not ready: {validation}")
        return 1

    runs_dir = Path(config.output.get("runs_dir", "outputs/runs"))

    if args.settings:
        settings = [s.strip() for s in args.settings.split(",")]
    else:
        settings = config.ablation.get("settings", list(ABLATION_SETTINGS))

    print(f"Settings to run: {settings}")
    print(f"Total: {len(settings)} settings")

    results = {}
    config_path = Path(args.config)

    for setting_name in settings:
        flags = ABLATION_SETTINGS.get(setting_name)
        if flags is None:
            print(f"  [SKIP] unknown ablation setting: {setting_name}")
            continue

        try:
            summary = run_single_setting(
                config=config,
                setting_name=setting_name,
                flags=flags,
                runs_dir=runs_dir,
                config_path=config_path,
                force=args.force,
            )
            results[setting_name] = {
                "status": "ok",
                "tuples": summary.get("num_tuples_generated", 0),
                "failures": summary.get("num_api_failures", 0),
            }
        except Exception as e:
            print(f"  [ERROR] {setting_name}: {e}")
            results[setting_name] = {"status": "error", "error": str(e)}

    print(f"\n\n{'='*60}")
    print("ABLATION RESULTS SUMMARY")
    print(f"{'='*60}")
    for name, result in results.items():
        if result["status"] == "ok":
            print(f"  {name}: tuples={result['tuples']}, failures={result['failures']}")
        else:
            print(f"  {name}: ERROR - {result['error']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())