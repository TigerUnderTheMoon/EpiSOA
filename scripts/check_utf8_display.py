"""Check UTF-8 readability and replacement-character damage in paper outputs.

This script is intentionally read-only. It helps distinguish real data damage
from terminal display issues on Windows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_SAMPLE_FILES = [
    Path("data/pubevent_soa_lite/events.jsonl"),
    Path("data/pubevent_soa_lite/evidence_filtered.jsonl"),
    Path("outputs/runs/paper_materials/results_tables.md"),
    Path("outputs/runs/paper_materials/case_studies.md"),
]

DEFAULT_SCAN_ROOTS = [
    Path("data/pubevent_soa_lite"),
    Path("outputs/runs/paper_materials"),
    Path("outputs/runs/schema_attribution"),
    Path("outputs/runs/faithfulness_verification"),
    Path("outputs/runs/event_chain_retrieval"),
]

TEXT_SUFFIXES = {".jsonl", ".json", ".md", ".csv", ".txt"}
REPLACEMENT_CHAR = "\ufffd"


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = build_parser().parse_args(argv)
    sample_files = [Path(item) for item in args.samples] if args.samples else DEFAULT_SAMPLE_FILES
    scan_roots = [Path(item) for item in args.scan_roots] if args.scan_roots else DEFAULT_SCAN_ROOTS

    print("UTF-8 sample preview")
    print("====================")
    for path in sample_files:
        print_sample(path, max_chars=args.max_chars)

    print()
    print("Replacement-character report")
    print("============================")
    report = scan_replacement_characters(scan_roots)
    if not report:
        print("No replacement characters found in scanned text files.")
    else:
        for path, count in report:
            print(f"{path}: {count}")
        print()
        print(
            "Note: replacement characters usually indicate text already lost during "
            "collection or earlier decoding. This script reports them but does not rewrite files."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview UTF-8 paper files and report replacement characters.")
    parser.add_argument("--samples", nargs="*", help="Files to preview. Defaults to key paper data/output files.")
    parser.add_argument("--scan-roots", nargs="*", help="Directories to scan for U+FFFD replacement characters.")
    parser.add_argument("--max-chars", type=int, default=320, help="Maximum text characters to print per sample.")
    return parser


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def print_sample(path: Path, *, max_chars: int) -> None:
    print()
    print(f"--- {path} ---")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print("MISSING")
        return
    except UnicodeDecodeError as exc:
        print(f"UTF-8 DECODE ERROR: {exc}")
        return

    snippet = sample_text(path, text, max_chars=max_chars)
    print(snippet if snippet else "(empty)")


def sample_text(path: Path, text: str, *, max_chars: int) -> str:
    if path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return truncate(line, max_chars)
            return truncate(format_jsonl_record(record), max_chars)
        return ""
    return truncate(text.strip().replace("\r\n", "\n"), max_chars)


def format_jsonl_record(record: dict[str, Any]) -> str:
    preferred_keys = [
        "event_id",
        "event_name",
        "event_description",
        "evidence_id",
        "source",
        "domain",
        "url",
        "text",
    ]
    parts = []
    for key in preferred_keys:
        if key in record and record[key] not in (None, ""):
            value = record[key]
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"{key}: {value}")
    if parts:
        return "\n".join(parts)
    return json.dumps(record, ensure_ascii=False)


def scan_replacement_characters(roots: list[Path]) -> list[tuple[Path, int]]:
    report: list[tuple[Path, int]] = []
    for root in roots:
        if root.is_file():
            count = replacement_count(root)
            if count:
                report.append((root, count))
            continue
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            count = replacement_count(path)
            if count:
                report.append((path, count))
    return report


def replacement_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    return text.count(REPLACEMENT_CHAR)


def truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
