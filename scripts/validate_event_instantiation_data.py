"""Validate topic seed, candidate event, and formal event data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from episoa.data.validator import validate_event_instantiation_data


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_event_instantiation_data(args.data_dir)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["hard_errors"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate PubEvent-SOA event instantiation data.")
    parser.add_argument("--data-dir", default="data/pubevent_soa_lite")
    parser.add_argument("--output", default=None)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
