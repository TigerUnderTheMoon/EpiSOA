"""Merge raw C-FSM post files without overwriting the originals."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Any

from episoa.data.loader import read_jsonl, write_jsonl


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = read_jsonl(args.base)
    extra = read_jsonl(args.extra) if Path(args.extra).exists() else []
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for item in [*base, *extra]:
        key = merge_key(item)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        merged.append(item)
    write_jsonl(args.output, merged)
    print(f"merged {len(base)} base + {len(extra)} extra into {len(merged)} rows at {args.output}")
    print(f"dropped {duplicates} duplicate rows")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge base and targeted recollection raw_posts JSONL files.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--extra", required=True)
    parser.add_argument("--output", required=True)
    return parser


def merge_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return "url:" + url
    raw_id = str(item.get("raw_id") or "").strip()
    if raw_id:
        return "raw_id:" + raw_id
    text = re.sub(r"\s+", "", str(item.get("text") or ""))[:300]
    return "text:" + hashlib.sha1(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
