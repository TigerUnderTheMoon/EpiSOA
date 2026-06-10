"""Run a single ablation setting by name.

Usage:
    python scripts/run_one_ablation.py full_soe [--force]
    python scripts/run_one_ablation.py direct_llm [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from episoa.pipeline import run_ablation_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run a single ablation setting")
    parser.add_argument("setting", help="Ablation setting name (e.g. full_soe, direct_llm)")
    parser.add_argument("--config", default="configs/ablation.yaml")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    # Create a temporary config that only lists the requested setting
    import yaml
    config_path = Path(args.config)
    with open(config_path, encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    # Override settings to just the one we want
    config_data["ablation"]["settings"] = [args.setting]

    # Write to a temp config
    tmp_config = Path("configs/ablation_single.yaml")
    with open(tmp_config, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

    try:
        result = run_ablation_pipeline(str(tmp_config), force=args.force)
        print(f"Result: {result.get('status', 'unknown')}")
        return 0
    finally:
        if tmp_config.exists():
            tmp_config.unlink()


if __name__ == "__main__":
    raise SystemExit(main())