"""Configuration loading and path isolation for the parallel EA pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

EA_ABLATION_SETTINGS = (
    "without_type_constraint",
    "without_dual_attribution",
    "without_field_level_verification",
)
EA_FUSION_ABLATION_SETTINGS = (
    "without_attribution_constraint",
    "without_cluster_consistency",
    "without_provenance_aware_source_deduplication",
)
FORBIDDEN_LEGACY_PATH_PARTS = ("pubevent_soa_lite", "runs_human_gold_v2")


class EAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., min_length=1)
    mode: Literal["ea_pilot", "ea_ablation"]
    data: dict[str, str]
    output: dict[str, str]
    runtime: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    ablation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> EAConfig:
        formal_dir = Path(self.data.get("viewpoint_effects_path", "formal/viewpoint_effects.jsonl")).parent
        process_dir = Path(self.data.get("effect_candidates_path", "process/effect_candidates.jsonl")).parent
        self.data.setdefault("semantic_pair_judgments_path", str(process_dir / "semantic_pair_judgments.jsonl"))
        self.data.setdefault("canonical_effects_path", str(formal_dir / "canonical_effects.jsonl"))
        self.data.setdefault("claim_pair_relations_path", str(formal_dir / "claim_pair_relations.jsonl"))
        self.data.setdefault("fusion_pair_judgments_path", str(process_dir / "fusion_pair_judgments.jsonl"))
        self.data.setdefault("fusion_cluster_diagnostics_path", str(process_dir / "fusion_cluster_diagnostics.jsonl"))
        self.data.setdefault("event_dossiers_path", str(formal_dir / "event_dossiers.jsonl"))
        required_data = {
            "raw_posts_path",
            "sources_path",
            "documents_path",
            "effect_candidates_path",
            "explanation_candidates_path",
            "relation_judgments_path",
            "evidence_links_path",
            "extraction_attempts_path",
            "m3_attempts_path",
            "verification_diagnostics_path",
            "viewpoint_effects_path",
            "attribution_claims_path",
            "semantic_pair_judgments_path",
            "canonical_effects_path",
            "canonical_claim_groups_path",
            "claim_pair_relations_path",
            "fusion_pair_judgments_path",
            "fusion_cluster_diagnostics_path",
            "canonical_adjudication_queue_path",
            "event_dossiers_path",
        }
        missing = sorted(required_data - self.data.keys())
        if missing:
            raise ValueError("missing EA data paths: " + ", ".join(missing))
        if "runs_dir" not in self.output or "cache_dir" not in self.output:
            raise ValueError("EA output requires runs_dir and cache_dir")
        threshold = float(self.evaluation.get("explanation_span_f1_threshold", 0.5))
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("explanation_span_f1_threshold must be within [0, 1]")
        chunk_size = int(self.runtime.get("chunk_size_chars", 6000))
        chunk_overlap = int(self.runtime.get("chunk_overlap_chars", 300))
        schema_retries = int(self.runtime.get("schema_retries", 1))
        if chunk_size <= 0:
            raise ValueError("chunk_size_chars must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap_chars must be within [0, chunk_size_chars)")
        if schema_retries < 0:
            raise ValueError("schema_retries must be non-negative")
        settings = list(self.ablation.get("settings", []))
        unknown = sorted(
            set(settings) - set(EA_ABLATION_SETTINGS) - set(EA_FUSION_ABLATION_SETTINGS)
        )
        if unknown:
            raise ValueError("unknown EA ablation settings: " + ", ".join(unknown))
        assert_isolated_paths(self)
        return self


def load_ea_config(path: str | Path) -> EAConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return EAConfig.model_validate(payload)


def assert_isolated_paths(config: EAConfig) -> None:
    for section, values in (("data", config.data), ("output", config.output)):
        for key, value in values.items():
            normalized = str(value).replace("\\", "/").lower()
            if any(part in normalized for part in FORBIDDEN_LEGACY_PATH_PARTS):
                raise ValueError(f"EA {section}.{key} overlaps a legacy path: {value}")
