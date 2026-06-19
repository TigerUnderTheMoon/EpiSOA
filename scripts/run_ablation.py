"""Run EpiSOA ablation experiments.

Usage:
  python scripts/run_ablation.py --config configs/ablation.yaml --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
while str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

from episoa.pipeline import run_ablation_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EpiSOA ablation experiments")
    parser.add_argument("--config", default="configs/ablation.yaml")
    parser.add_argument("--force", action="store_true",
                        help="Remove existing setting directories before re-running all settings")
    parser.add_argument("--resume", action="store_true", default=None)
    parser.add_argument("--max-api-concurrency", type=int, default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--diagnostic", action="store_true", default=None)
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--event-ids", default=None, help="Comma-separated event IDs for diagnostic runs")
    parser.add_argument("--settings", default=None, help="Comma-separated ablation settings to run")
    parser.add_argument("--skip-llm-verifier", action="store_true", default=None)
    args = parser.parse_args(argv)
    result = run_ablation_pipeline(
        args.config,
        force=args.force,
        resume=args.resume,
        max_api_concurrency=args.max_api_concurrency,
        cache_dir=args.cache_dir,
        diagnostic=args.diagnostic,
        max_events=args.max_events,
        event_ids=_split_csv(args.event_ids),
        settings=_split_csv(args.settings),
        skip_llm_verifier=args.skip_llm_verifier,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
