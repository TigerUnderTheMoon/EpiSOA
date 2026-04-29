"""Tuple parser facade based on the canonical Pydantic schema."""

from __future__ import annotations

from typing import Any

from episoa.schemas.attribution import AttributionTuple


def parse_attribution_tuple(payload: dict[str, Any]) -> AttributionTuple:
    return AttributionTuple.model_validate(payload)


__all__ = ["parse_attribution_tuple"]
