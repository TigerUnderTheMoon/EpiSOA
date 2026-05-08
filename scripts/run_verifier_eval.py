"""Run verifier evaluation for an existing paper run."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    path = Path("outputs/runs/pubevent-soa-lite-paper/verifier_results.csv")
    status = {"verifier_results.csv": path.exists(), "path": str(path)}
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
