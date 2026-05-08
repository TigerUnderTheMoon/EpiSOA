"""Normalize raw C-FSM posts into the traceable evidence pool."""

from __future__ import annotations

import argparse
from pathlib import Path

from episoa.data.loader import read_jsonl, write_jsonl


RAW_POSTS_PATH = Path("data/pubevent_soa_lite/raw/raw_posts.jsonl")
EVIDENCE_PATH = Path("data/pubevent_soa_lite/evidence.jsonl")
CANDIDATES_PATH = Path("data/pubevent_soa_lite/interim/evidence_candidates.jsonl")
DUPLICATE_REPORT_PATH = Path("data/pubevent_soa_lite/interim/duplicate_report.csv")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return normalize(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize raw C-FSM posts into evidence JSONL.")
    parser.add_argument("--input", default=str(RAW_POSTS_PATH))
    parser.add_argument("--output", default=str(EVIDENCE_PATH))
    parser.add_argument("--candidates-output", default=str(CANDIDATES_PATH))
    parser.add_argument("--duplicate-report", default=str(DUPLICATE_REPORT_PATH))
    return parser


def normalize(args: argparse.Namespace) -> int:
    raw_posts_path = Path(args.input)
    evidence_path = Path(args.output)
    candidates_path = Path(args.candidates_output)
    duplicate_report_path = Path(args.duplicate_report)
    raw_posts = read_jsonl(raw_posts_path) if raw_posts_path.exists() else []
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    duplicate_report_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_posts:
        evidence_path.write_text("", encoding="utf-8")
        candidates_path.write_text("", encoding="utf-8")
        duplicate_report_path.write_text("duplicate_key,raw_ids,action\n", encoding="utf-8")
        print("WARNING: raw_posts.jsonl is empty; evidence.jsonl was left empty.")
        return 0

    seen: set[str] = set()
    evidence = []
    duplicates = ["duplicate_key,raw_ids,action"]
    for index, raw in enumerate(raw_posts, start=1):
        key = str(raw.get("url") or raw.get("text") or raw.get("raw_id"))
        if key in seen:
            duplicates.append(f"{key},{raw.get('raw_id')},dropped")
            continue
        seen.add(key)
        evidence.append(
            {
                "evidence_id": f"ev-{index:05d}",
                "event_id": raw.get("event_id"),
                "source": raw.get("source"),
                "platform": raw.get("platform"),
                "publish_time": raw.get("publish_time"),
                "url": raw.get("url"),
                "text": raw.get("text"),
                "stakeholder_hint": None,
                "stance_hint": None,
                "temporal_stage": None,
                "traceable": bool(raw.get("url") or raw.get("source")),
            }
        )
    write_jsonl(candidates_path, evidence)
    write_jsonl(evidence_path, evidence)
    duplicate_report_path.write_text("\n".join(duplicates) + "\n", encoding="utf-8")
    print(f"wrote {len(evidence)} normalized evidence records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
