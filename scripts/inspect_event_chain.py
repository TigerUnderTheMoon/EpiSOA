"""Print one candidate event chain for human audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candidate = find_candidate(Path(args.input), args.event_id)
    if candidate is None:
        print(f"event_id not found: {args.event_id}")
        return 1

    print(f"event_id: {candidate.get('event_id')}")
    print(f"chain_confidence: {candidate.get('chain_confidence')}")
    print(f"missing_stages: {', '.join(candidate.get('missing_stages', [])) or 'none'}")
    for stage in candidate.get("stages", []):
        print("")
        print(f"stage: {stage.get('stage')}")
        evidence_items = stage.get("evidence", [])
        if not evidence_items:
            print("  no evidence selected")
            continue
        for evidence in evidence_items:
            print(f"  evidence_id: {evidence.get('evidence_id')}")
            print(f"  final_stage_score: {evidence.get('final_stage_score')}")
            print(f"  event_relevance_score: {evidence.get('event_relevance_score')}")
            print(f"  matched_event_terms: {join_terms(evidence.get('matched_event_terms', []))}")
            print(f"  matched_seed_keywords: {join_terms(evidence.get('matched_seed_keywords', []))}")
            print(f"  matched_stage_keywords: {join_terms(evidence.get('matched_stage_keywords', []))}")
            print(f"  source: {evidence.get('source')}")
            print(f"  domain: {evidence.get('domain')}")
            print(f"  title: {evidence.get('title')}")
            print(f"  text_excerpt: {evidence.get('text_excerpt')}")
            print(f"  url: {evidence.get('url')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect one retrieved EpiSOA candidate event chain.")
    parser.add_argument("--input", default="outputs/runs/event_chain_retrieval/event_chain_candidates.jsonl")
    parser.add_argument("--event-id", required=True)
    return parser


def find_candidate(path: Path, event_id: str) -> dict | None:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event_id") == event_id:
                return row
    return None


def join_terms(values: object) -> str:
    if isinstance(values, list):
        return "|".join(str(value) for value in values)
    return str(values or "")


if __name__ == "__main__":
    raise SystemExit(main())
