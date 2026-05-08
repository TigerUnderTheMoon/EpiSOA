"""Run the main EpiSOA paper experiment."""

from __future__ import annotations

import argparse
import json

from episoa.pipeline import run_paper_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/paper.yaml")
    args = parser.parse_args(argv)
    print(json.dumps(run_paper_pipeline(args.config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
