"""JSONL loading utilities for the paper workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

T = TypeVar("T", bound=BaseModel)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"required file not found: {path}")
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must be a JSON object")
        records.append(value)
    return records


def read_typed_jsonl(path: str | Path, model: type[T]) -> list[T]:
    adapter = TypeAdapter(model)
    output: list[T] = []
    for line_number, record in enumerate(read_jsonl(path), start=1):
        try:
            output.append(adapter.validate_python(record))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number} failed schema validation: {exc}") from exc
    return output


def write_jsonl(path: str | Path, records: Iterable[BaseModel | dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for record in records:
        if isinstance(record, BaseModel):
            lines.append(record.model_dump_json(exclude_none=True))
        else:
            lines.append(json.dumps(record, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
