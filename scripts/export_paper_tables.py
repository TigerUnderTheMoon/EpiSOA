"""Export paper tables from run artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def export_tables(run_dir: str | Path = "outputs/runs/pubevent-soa-lite-paper") -> dict[str, bool]:
    run_dir = Path(run_dir)
    outputs: dict[str, bool] = {}
    for name in ("main_results.csv", "ablation_results.csv", "retrieval_results.csv", "verifier_results.csv", "case_studies.jsonl"):
        source = run_dir / name
        outputs[name] = source.exists()
        if source.exists():
            shutil.copyfile(source, run_dir / name)
    return outputs


def main() -> int:
    print(json.dumps(export_tables(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
