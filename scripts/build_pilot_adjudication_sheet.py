#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Export pilot adjudication sheets from the full human review sheets."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_HUMAN_DIR = Path("data/pubevent_soa_lite/human_gold_v1")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_pilot_sheets(
        pilot_events_path=Path(args.pilot_events),
        tuple_sheet=Path(args.tuple_sheet),
        chain_sheet=Path(args.chain_sheet),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build pilot adjudication CSV sheets.")
    parser.add_argument("--pilot-events", default=str(DEFAULT_HUMAN_DIR / "pilot_events_v1.json"))
    parser.add_argument("--tuple-sheet", default=str(DEFAULT_HUMAN_DIR / "human_tuple_adjudication_sheet.csv"))
    parser.add_argument("--chain-sheet", default=str(DEFAULT_HUMAN_DIR / "human_chain_adjudication_sheet.csv"))
    parser.add_argument("--output-dir", default=str(DEFAULT_HUMAN_DIR))
    return parser


def build_pilot_sheets(
    *,
    pilot_events_path: Path,
    tuple_sheet: Path,
    chain_sheet: Path,
    output_dir: Path,
) -> dict[str, Any]:
    event_ids = read_pilot_event_ids(pilot_events_path)
    tuple_rows, tuple_fields = read_csv_with_fields(tuple_sheet)
    chain_rows, chain_fields = read_csv_with_fields(chain_sheet)
    pilot_tuples = [row for row in tuple_rows if row.get("event_id") in event_ids]
    pilot_chains = [row for row in chain_rows if row.get("event_id") in event_ids]
    output_dir.mkdir(parents=True, exist_ok=True)
    tuple_out = output_dir / "human_tuple_adjudication_sheet_pilot5.csv"
    chain_out = output_dir / "human_chain_adjudication_sheet_pilot5.csv"
    write_csv(tuple_out, tuple_fields, pilot_tuples)
    write_csv(chain_out, chain_fields, pilot_chains)
    missing_tuple_events = sorted(event_ids - {row.get("event_id") for row in pilot_tuples})
    missing_chain_events = sorted(event_ids - {row.get("event_id") for row in pilot_chains})
    return {
        "pilot_events": sorted(event_ids),
        "tuple_rows": len(pilot_tuples),
        "chain_rows": len(pilot_chains),
        "tuple_sheet_out": str(tuple_out),
        "chain_sheet_out": str(chain_out),
        "missing_tuple_events": missing_tuple_events,
        "missing_chain_events": missing_chain_events,
    }


def read_pilot_event_ids(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = {str(row.get("event_id")) for row in payload.get("events", []) if row.get("event_id")}
    if len(ids) != 5:
        raise ValueError(f"expected 5 pilot events, got {len(ids)}")
    return ids


def read_csv_with_fields(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    backup_existing(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def backup_existing(path: Path) -> None:
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak_{timestamp}"))


if __name__ == "__main__":
    raise SystemExit(main())
