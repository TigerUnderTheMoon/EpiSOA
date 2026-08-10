"""Single-mechanism M4 ablation matrix and isolation checks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AblationId = Literal[
    "full",
    "without_type_constraint",
    "without_dual_attribution",
    "without_field_level_verification",
]


class MechanismVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_constraint: bool = True
    dual_attribution: bool = True
    field_level_verification: bool = True


class AblationControls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_set_hash: str = Field(..., min_length=1)
    gold_version: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    prompt_base_version: str = Field(..., min_length=1)
    decoding_version: str = Field(..., min_length=1)
    normalization_version: str = Field(..., min_length=1)
    evaluator_version: str = Field(..., min_length=1)
    seed: int


class AblationRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: AblationId
    mechanisms: MechanismVector
    controls: AblationControls
    output_path: str = Field(..., min_length=1)


class AblationMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[AblationRunSpec] = Field(..., min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_isolation(self) -> AblationMatrix:
        by_id = {row.run_id: row for row in self.runs}
        required = {
            "full",
            "without_type_constraint",
            "without_dual_attribution",
            "without_field_level_verification",
        }
        if set(by_id) != required or len(by_id) != len(self.runs):
            raise ValueError(
                "ablation matrix must contain full plus the frozen three settings"
            )
        full = by_id["full"]
        if full.mechanisms != MechanismVector():
            raise ValueError("full setting must enable every mechanism")
        for run_id, expected_field in {
            "without_type_constraint": "type_constraint",
            "without_dual_attribution": "dual_attribution",
            "without_field_level_verification": "field_level_verification",
        }.items():
            variant = by_id[run_id]
            if variant.controls != full.controls:
                raise ValueError(
                    f"{run_id} changes controls in addition to one mechanism"
                )
            changed = [
                field
                for field in MechanismVector.model_fields
                if getattr(full.mechanisms, field) != getattr(variant.mechanisms, field)
            ]
            if changed != [expected_field] or getattr(
                variant.mechanisms, expected_field
            ):
                raise ValueError(f"{run_id} must disable only {expected_field}")
        return self


def build_ablation_matrix(
    controls: AblationControls, *, output_root: str
) -> AblationMatrix:
    return AblationMatrix(
        runs=[
            AblationRunSpec(
                run_id="full",
                mechanisms=MechanismVector(),
                controls=controls,
                output_path=f"{output_root}/full",
            ),
            AblationRunSpec(
                run_id="without_type_constraint",
                mechanisms=MechanismVector(type_constraint=False),
                controls=controls,
                output_path=f"{output_root}/without_type_constraint",
            ),
            AblationRunSpec(
                run_id="without_dual_attribution",
                mechanisms=MechanismVector(dual_attribution=False),
                controls=controls,
                output_path=f"{output_root}/without_dual_attribution",
            ),
            AblationRunSpec(
                run_id="without_field_level_verification",
                mechanisms=MechanismVector(field_level_verification=False),
                controls=controls,
                output_path=f"{output_root}/without_field_level_verification",
            ),
        ]
    )


FusionAblationId = Literal[
    "full_apcf",
    "without_attribution_constraint",
    "without_cluster_consistency",
    "without_provenance_aware_source_deduplication",
]


class FusionMechanismVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribution_constraint: bool = True
    cluster_consistency: bool = True
    provenance_aware_source_deduplication: bool = True


class FusionAblationRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: FusionAblationId
    mechanisms: FusionMechanismVector
    controls: AblationControls
    judgment_resource_id: str = Field(..., min_length=1)
    output_path: str = Field(..., min_length=1)


class FusionAblationMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[FusionAblationRunSpec] = Field(..., min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_isolation(self) -> FusionAblationMatrix:
        by_id = {row.run_id: row for row in self.runs}
        required = {
            "full_apcf",
            "without_attribution_constraint",
            "without_cluster_consistency",
            "without_provenance_aware_source_deduplication",
        }
        if set(by_id) != required:
            raise ValueError("fusion ablation matrix must contain the frozen settings")
        full = by_id["full_apcf"]
        for run_id, expected in {
            "without_attribution_constraint": "attribution_constraint",
            "without_cluster_consistency": "cluster_consistency",
            "without_provenance_aware_source_deduplication": "provenance_aware_source_deduplication",
        }.items():
            row = by_id[run_id]
            if row.controls != full.controls:
                raise ValueError(f"{run_id} changed common controls")
            if row.judgment_resource_id != full.judgment_resource_id:
                raise ValueError(f"{run_id} changed semantic judgment resource")
            changed = [
                field
                for field in FusionMechanismVector.model_fields
                if getattr(row.mechanisms, field)
                != getattr(full.mechanisms, field)
            ]
            if changed != [expected] or getattr(row.mechanisms, expected):
                raise ValueError(f"{run_id} must disable only {expected}")
        return self


def build_fusion_ablation_matrix(
    controls: AblationControls,
    *,
    judgment_resource_id: str,
    output_root: str,
) -> FusionAblationMatrix:
    settings = [
        ("full_apcf", FusionMechanismVector()),
        (
            "without_attribution_constraint",
            FusionMechanismVector(attribution_constraint=False),
        ),
        (
            "without_cluster_consistency",
            FusionMechanismVector(cluster_consistency=False),
        ),
        (
            "without_provenance_aware_source_deduplication",
            FusionMechanismVector(provenance_aware_source_deduplication=False),
        ),
    ]
    return FusionAblationMatrix(
        runs=[
            FusionAblationRunSpec(
                run_id=run_id,
                mechanisms=mechanisms,
                controls=controls,
                judgment_resource_id=judgment_resource_id,
                output_path=f"{output_root}/{run_id}",
            )
            for run_id, mechanisms in settings
        ]
    )
