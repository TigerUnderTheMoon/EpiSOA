"""Evaluation schemas for EpiSOA experiments and benchmarks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episoa.schemas.attribution import AttributionTuple


class EvaluationSample(BaseModel):
    """A labeled example used to evaluate EpiSOA output."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(..., min_length=1, description="Unique identifier for the evaluation sample.")
    query: str = Field(..., min_length=1, description="Input query or task description for the sample.")
    expected: list[AttributionTuple] = Field(default_factory=list, description="Reference attribution tuples.")
    predicted: list[AttributionTuple] = Field(default_factory=list, description="Model-produced attribution tuples.")
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="Optional scalar metadata for grouping or filtering evaluation results.",
    )

    @field_validator("sample_id", "query", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class MetricScore(BaseModel):
    """A bounded evaluation metric value."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Metric name.")
    value: float = Field(..., ge=0.0, le=1.0, description="Metric value in the range [0, 1].")
    details: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="Optional scalar details for the metric.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("name must be a string")
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value
