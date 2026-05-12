"""Normalize source_type field in evidence JSONL.

Maps source/platform/url → canonical source_type:
  official → official
  news → mainstream_news
  public_social → social_media
  public_interaction → public_interaction
  forum → forum
  public_web → infers from domain (official/mainstream_news/social_media/
               public_interaction/forum/public_web)

Automatically backs up the original file before writing.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from episoa.data.loader import read_jsonl, write_jsonl

CANONICAL_EVIDENCE = Path("data/pubevent_soa_lite/evidence_v3_repaired_plus_low37.jsonl")
SOURCE_DETECTION_CONFIG = Path("configs/source_detection.yaml")

DIRECT_MAP: dict[str, str] = {
    "official": "official",
    "news": "mainstream_news",
    "public_social": "social_media",
    "public_interaction": "public_interaction",
    "forum": "forum",
}

CANONICAL_SOURCE_TYPES = {"official", "mainstream_news", "social_media", "forum", "public_interaction", "public_web"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return normalize(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize source_type field in evidence JSONL."
    )
    parser.add_argument("--input", default=str(CANONICAL_EVIDENCE),
                        help="Path to evidence JSONL file")
    parser.add_argument("--output", default=None,
                        help="Output path (default: overwrite input after backup)")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip automatic backup of original file")
    parser.add_argument("--source-detection-config", default=str(SOURCE_DETECTION_CONFIG),
                        help="Path to source_detection.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report changes without writing")
    return parser


def normalize(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    source_detection_path = Path(args.source_detection_config)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        return 1

    if not source_detection_path.exists():
        print(f"ERROR: source detection config not found: {source_detection_path}")
        return 1

    evidence = read_jsonl(str(input_path))
    if not evidence:
        print("No evidence records found.")
        return 1

    domain_rules = _load_domain_rules(source_detection_path)

    stats_before: dict[str, int] = {}
    stats_after: dict[str, int] = {}
    changed = 0
    missing_before = 0

    for ev in evidence:
        old_st = ev.get("source_type") or "MISSING"
        stats_before[old_st] = stats_before.get(old_st, 0) + 1
        if old_st == "MISSING":
            missing_before += 1

        source = ev.get("source", "")
        platform = ev.get("platform", "")
        url = ev.get("url", "")

        new_st = _infer_source_type(source, platform, url, domain_rules)
        if old_st != new_st:
            ev["source_type"] = new_st
            changed += 1

        stats_after[new_st] = stats_after.get(new_st, 0) + 1

    if args.dry_run:
        print("[DRY RUN] Would make the following changes:\n")
        print(f"  {len(evidence)} evidence records scanned")
        print(f"  {changed} records would have source_type updated")
        print(f"  {missing_before} records had missing source_type before")
        print("\n  source_type distribution (before → after):")
        all_types = sorted(set(list(stats_before.keys()) + list(stats_after.keys())))
        for st in all_types:
            print(f"    {st}: {stats_before.get(st, 0)} → {stats_after.get(st, 0)}")
        return 0

    output_path = Path(args.output) if args.output else input_path

    if not args.no_backup and output_path == input_path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = input_path.with_suffix(f".jsonl.bak_{timestamp}")
        shutil.copy2(input_path, backup_path)
        print(f"Backed up original to: {backup_path}")

    write_jsonl(str(output_path), evidence)

    print(f"Normalized {len(evidence)} evidence records ({changed} changed)")
    print(f"Missing source_type before: {missing_before}")
    print(f"source_type distribution:")
    for st in sorted(stats_after.keys()):
        print(f"  {st}: {stats_after[st]}")

    return 0


def _infer_source_type(
    source: str,
    platform: str,
    url: str,
    domain_rules: dict[str, Any],
) -> str:
    if source in DIRECT_MAP:
        return DIRECT_MAP[source]

    if source == "public_web" or not source:
        return _infer_from_domain(url, platform, domain_rules)

    return source if source in CANONICAL_SOURCE_TYPES else "public_web"


def _infer_from_domain(url: str, platform: str, domain_rules: dict[str, Any]) -> str:
    domain = platform or ""
    if not domain and url:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.hostname or ""
        except Exception:
            pass

    domain_lower = domain.lower()

    official_domains = domain_rules.get("official_domains", [])
    interaction_domains = domain_rules.get("interaction_domains", [])
    news_domains = domain_rules.get("news_domains", [])
    forum_domains = domain_rules.get("forum_domains", [])
    social_domains = domain_rules.get("social_domains", [])

    if domain_lower:
        for od in official_domains:
            if domain_lower.endswith(od.lower()):
                return "official"
        for nd in news_domains:
            if nd.lower() in domain_lower:
                return "mainstream_news"
        for sd in social_domains:
            if sd.lower() in domain_lower:
                return "social_media"
        for fd in forum_domains:
            if fd.lower() in domain_lower:
                return "forum"
        for idm in interaction_domains:
            if idm.lower() in domain_lower:
                return "public_interaction"

    return "public_web"


def _load_domain_rules(config_path: Path) -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


if __name__ == "__main__":
    raise SystemExit(main())
