"""Resume ablation experiment — run only missing settings.

Usage:  python scripts/_resume_ablation.py

Reads existing metrics from completed settings in
outputs/runs/ablation_{setting}/ and runs only the missing ones.
Unlike run_ablation.py (paper-final mode, always re-runs), this
script retains SKIP logic for development convenience.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from episoa.config import load_config, print_api_config_status
from episoa.data.loader import read_typed_jsonl
from episoa.data.schema import EventRecord, EvidenceRecord, GoldEventChain, GoldTuple
from episoa.data.validator import validate_paper_data
from episoa.evaluation.evaluate_ablation import evaluate_ablation
from episoa.pipeline import (
    ABLATION_SETTINGS,
    _create_llm_client,
    _get_git_commit,
    _run_core_pipeline,
    _write_ablation_csv,
    _write_event_level_csv,
    _write_input_manifest,
    _write_prompt_manifest,
)


def main() -> int:
    config = load_config("configs/ablation.yaml")
    print_api_config_status(config)
    validation = validate_paper_data()
    runs_dir = Path(config.output.get("runs_dir", "outputs/runs"))

    if not validation["paper_data_ready"]:
        print("ERROR: paper data is not ready")
        return 1

    events = read_typed_jsonl(config.data["events_path"], EventRecord)
    evidence = read_typed_jsonl(config.data["evidence_path"], EvidenceRecord)
    gold = read_typed_jsonl(config.data["gold_tuples_path"], GoldTuple)
    gold_chains = read_typed_jsonl(
        config.data["gold_event_chains_path"], GoldEventChain
    )

    llm_client = _create_llm_client(config)
    timestamp = datetime.now(timezone.utc).isoformat()
    git_commit = _get_git_commit()

    all_metrics: dict[str, dict[str, float]] = {}
    settings: list[str] = config.ablation.get("settings", list(ABLATION_SETTINGS))

    for setting in settings:
        flags = ABLATION_SETTINGS.get(setting)
        if flags is None:
            print(f"  [SKIP] unknown ablation setting: {setting}")
            continue

        setting_dir = runs_dir / f"ablation_{setting}"
        existing_metrics = setting_dir / "metrics.json"

        if existing_metrics.exists():
            m = json.loads(existing_metrics.read_text(encoding="utf-8"))
            f1 = m.get("Tuple-F1-soft", m.get("Tuple-F1", 0))
            num_tuples = m.get("Num-Tuples", 0)
            if isinstance(f1, (int, float)) and isinstance(num_tuples, (int, float)):
                if f1 > 0 or num_tuples > 0:
                    print(f"  [SKIP] {setting}: already done (Tuple-F1-soft={f1}, {num_tuples} tuples)")
                    all_metrics[setting] = m
                    continue
            print(f"  [RERUN] {setting}: previous run had {num_tuples} tuples, F1={f1}")

        print(f"  [RUN] {setting} → {setting_dir}")
        setting_dir.mkdir(parents=True, exist_ok=True)

        shutil.copyfile("configs/ablation.yaml", setting_dir / "config_snapshot.yaml")
        _write_input_manifest(
            setting_dir,
            run_id=f"ablation_{setting}",
            timestamp=timestamp,
            git_commit=git_commit,
            setting=setting,
            config=config,
            events_count=len(events),
            evidence_count=len(evidence),
            gold_count=len(gold),
            flags=flags,
        )
        _write_prompt_manifest(setting_dir, config)

        verified, _retrieval_metrics, _verifier_metrics = _run_core_pipeline(
            events, evidence, gold, gold_chains, config, setting_dir, llm_client,
            **flags,
        )

        metrics = evaluate_ablation(gold, verified)
        all_metrics[setting] = metrics

        (setting_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_event_level_csv(setting_dir / "event_level_metrics.csv", gold, verified)
        print(f"  [{setting}] Tuple-F1-soft={metrics.get('Tuple-F1-soft', 'N/A')}, "
              f"Num-Tuples={metrics.get('Num-Tuples', 'N/A')}")

    # Write final comparison (aggregates from current run + skipped-cached)
    _write_ablation_csv(runs_dir / "ablation_results.csv", all_metrics)
    summary = {
        "status": "completed",
        "run_id": "ablation",
        "timestamp": timestamp,
        "git_commit": git_commit,
        "settings": list(all_metrics.keys()),
        "metrics": all_metrics,
    }
    (runs_dir / "ablation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print("=== Final Results ===")
    print((runs_dir / "ablation_results.csv").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
