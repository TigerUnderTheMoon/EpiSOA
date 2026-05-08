"""Validate PubEvent-SOA Lite paper data."""

from __future__ import annotations

import json

from episoa.data.validator import validate_paper_data


def main() -> int:
    report = validate_paper_data()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
