"""Run EpiSOA ablation experiments.

Usage:
  python scripts/run_ablation.py --config configs/ablation.yaml
  python scripts/run_ablation.py --config configs/ablation.yaml --force
"""

from __future__ import annotations

import argparse
import json

from episoa.pipeline import run_ablation_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EpiSOA ablation experiments")
    parser.add_argument("--config", default="configs/ablation.yaml")
    parser.add_argument("--force", action="store_true",
                        help="Re-run all settings even if metrics.json already exists")
    args = parser.parse_args(argv)
    result = run_ablation_pipeline(args.config, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
