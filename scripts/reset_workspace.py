"""Reset generated PubEvent-SOA data and output artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


DATA_DIR = Path("data/pubevent_soa_lite")
OUTPUTS_DIR = Path("outputs")
SKELETON_DIRS = [
    DATA_DIR / "raw",
    DATA_DIR / "interim",
    DATA_DIR / "annotation",
]
LEGACY_PATHS = [
    DATA_DIR / ("topic" + "_seeds.jsonl"),
    DATA_DIR / ("candidate_event" + "_instances.jsonl"),
    DATA_DIR / "discovery",
    DATA_DIR / "events_full.jsonl",
    DATA_DIR / "graph",
]
FORMAL_GENERATED_FILES = [
    DATA_DIR / "evidence.jsonl",
    DATA_DIR / "gold_tuples.jsonl",
    DATA_DIR / "gold_event_chains.jsonl",
    DATA_DIR / "gold_conversion_report.json",
    DATA_DIR / "gold_validation_report.json",
]


def main() -> int:
    report = reset_workspace()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def reset_workspace() -> dict:
    deleted: list[str] = []
    recreated: list[str] = []

    for directory in SKELETON_DIRS:
        deleted.extend(_delete_directory_contents(directory))
        directory.mkdir(parents=True, exist_ok=True)
        keep = directory / ".gitkeep"
        keep.write_text("", encoding="utf-8")
        recreated.append(str(keep))

    for path in [*LEGACY_PATHS, *FORMAL_GENERATED_FILES]:
        if path.exists():
            _delete_path(path)
            deleted.append(str(path))

    events_path = DATA_DIR / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text("", encoding="utf-8")
    recreated.append(str(events_path))

    for directory_name in ("runs", "cache"):
        deleted.extend(_delete_directory_contents(OUTPUTS_DIR / directory_name))
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    outputs_keep = OUTPUTS_DIR / ".gitkeep"
    outputs_keep.write_text("", encoding="utf-8")
    recreated.append(str(outputs_keep))

    return {"deleted": deleted, "recreated": recreated}


def _delete_directory_contents(directory: Path) -> list[str]:
    deleted: list[str] = []
    if not directory.exists():
        return deleted
    for child in directory.iterdir():
        if child.name == ".gitkeep":
            continue
        _delete_path(child)
        deleted.append(str(child))
    return deleted


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
