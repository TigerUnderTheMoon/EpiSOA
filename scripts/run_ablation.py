"""Run EpiSOA ablation experiments."""

from __future__ import annotations

import argparse
import json

from episoa.pipeline import run_ablation_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/ablation.yaml")
    args = parser.parse_args(argv)
    print(json.dumps(run_ablation_pipeline(args.config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
