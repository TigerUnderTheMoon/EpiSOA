"""Main comparison registry, applicability, and Long-context capacity gates."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from episoa.ea.evaluation import (
    EVALUATOR_VERSION,
    METHOD_IDS,
    NORMALIZATION_VERSION,
    MethodId,
)


class BaselineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_id: MethodId
    display_name: str
    method_type: Literal[
        "direct_generation", "pair_classifier", "prior_method", "proposed_method"
    ]
    requires_evidence: bool
    supports_dual_attribution: bool
    supports_field_verification: bool
    missing_field_policy: Literal["preserve_missing", "not_applicable"] = (
        "preserve_missing"
    )
    supports_effect: bool
    supports_relation: bool
    supports_claim: bool
    supports_event_dossier: bool


METHOD_SPECS = (
    BaselineSpec(
        method_id="long_context_event_llm",
        display_name="Long-context Event LLM",
        method_type="direct_generation",
        requires_evidence=False,
        supports_dual_attribution=True,
        supports_field_verification=False,
        supports_effect=True,
        supports_relation=True,
        supports_claim=True,
        supports_event_dossier=True,
    ),
    BaselineSpec(
        method_id="long_context_event_llm_evidence",
        display_name="Long-context Event LLM + Evidence Requirement",
        method_type="direct_generation",
        requires_evidence=True,
        supports_dual_attribution=True,
        supports_field_verification=False,
        supports_effect=True,
        supports_relation=True,
        supports_claim=True,
        supports_event_dossier=True,
    ),
    BaselineSpec(
        method_id="direct_pair_classification",
        display_name="Direct Explanation–Effect Pair Classification",
        method_type="pair_classifier",
        requires_evidence=True,
        supports_dual_attribution=True,
        supports_field_verification=False,
        supports_effect=False,
        supports_relation=True,
        supports_claim=False,
        supports_event_dossier=False,
    ),
    BaselineSpec(
        method_id="original_episoa",
        display_name="Original EpiSOA",
        method_type="prior_method",
        requires_evidence=True,
        supports_dual_attribution=False,
        supports_field_verification=False,
        supports_effect=True,
        supports_relation=True,
        supports_claim=True,
        supports_event_dossier=False,
    ),
    BaselineSpec(
        method_id="episoa_ea",
        display_name="EpiSOA-EA",
        method_type="proposed_method",
        requires_evidence=True,
        supports_dual_attribution=True,
        supports_field_verification=True,
        supports_effect=True,
        supports_relation=True,
        supports_claim=True,
        supports_event_dossier=True,
    ),
)


class FairnessProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_set_hash: str = Field(..., min_length=1)
    gold_version: str = Field(..., min_length=1)
    label_space_version: str = "ea-labels-v1"
    normalization_version: str = NORMALIZATION_VERSION
    evaluator_version: str = EVALUATOR_VERSION
    split_version: str = Field(..., min_length=1)


class MethodRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_id: MethodId
    protocol: FairnessProtocol
    model_name: str = Field(..., min_length=1)
    prompt_version: str = Field(..., min_length=1)
    decoding_version: str = Field(..., min_length=1)
    seed: int
    output_path: str = Field(..., min_length=1)
    adapter_version: str = "ea-common-adapter-v1"
    candidate_set_hash: str = "not_applicable"
    judgment_resource_id: str = "not_applicable"
    token_budget: int = Field(default=0, ge=0)
    failure_policy: str = "capacity_failure_is_not_false_negative"


class ComparisonManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[MethodRunManifest] = Field(..., min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_fairness(self) -> ComparisonManifest:
        ids = [row.method_id for row in self.runs]
        if len(set(ids)) != len(ids) or set(ids) != set(METHOD_IDS):
            raise ValueError("comparison must contain each frozen method exactly once")
        protocols = {
            row.protocol.model_dump_json(exclude_none=True) for row in self.runs
        }
        if len(protocols) != 1:
            raise ValueError(
                "all methods must share Document set, Gold, labels, normalizer, evaluator, and split"
            )
        llm_models = {
            row.model_name
            for row in self.runs
            if row.method_id
            in {
                "long_context_event_llm",
                "long_context_event_llm_evidence",
                "episoa_ea",
            }
        }
        if len(llm_models) != 1:
            raise ValueError(
                "Long-context methods and EpiSOA-EA must share one base LLM/version"
            )
        return self


class LongContextFreezeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    context_window_tokens: int = Field(..., gt=0)
    reserved_output_tokens: int = Field(..., gt=0)
    event_input_tokens: dict[str, int]
    frozen_before_formal_inference: bool
    formal_results_seen: bool = False

    @model_validator(mode="after")
    def validate_capacity_and_freeze(self) -> LongContextFreezeManifest:
        if self.formal_results_seen:
            raise ValueError("model freeze must occur before Formal results are seen")
        if not self.frozen_before_formal_inference:
            raise ValueError("Long-context model must be frozen before inference")
        overflow = {
            event_id: tokens
            for event_id, tokens in self.event_input_tokens.items()
            if tokens + self.reserved_output_tokens > self.context_window_tokens
        }
        if overflow:
            raise ValueError(f"Long-context capacity is insufficient: {overflow}")
        return self


class LongContextRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    status: Literal["success", "capacity_failure", "model_error"]
    input_tokens: int = Field(..., ge=0)
    raw_output: dict | None = None
    error: str | None = None


class LongContextClient(Protocol):
    def chat(self, *, system_prompt: str, user_prompt: str, response_format=None): ...


def preflight_long_context(
    event_inputs: dict[str, str],
    *,
    token_counter: Callable[[str], int],
    model_name: str,
    model_version: str,
    provider: str,
    context_window_tokens: int,
    reserved_output_tokens: int,
) -> LongContextFreezeManifest:
    return LongContextFreezeManifest(
        model_name=model_name,
        model_version=model_version,
        provider=provider,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        event_input_tokens={
            event_id: token_counter(text) for event_id, text in sorted(event_inputs.items())
        },
        frozen_before_formal_inference=True,
    )


def run_long_context_adapter(
    event_inputs: dict[str, str],
    *,
    client: LongContextClient,
    freeze: LongContextFreezeManifest,
    requires_evidence: bool,
) -> list[LongContextRunResult]:
    """Run one request per Event; never truncate or reinterpret overflow as FN."""
    output = []
    for event_id, text in sorted(event_inputs.items()):
        input_tokens = freeze.event_input_tokens.get(event_id)
        if input_tokens is None:
            raise ValueError(f"event was not covered by frozen tokenization: {event_id}")
        if input_tokens + freeze.reserved_output_tokens > freeze.context_window_tokens:
            output.append(
                LongContextRunResult(
                    event_id=event_id,
                    status="capacity_failure",
                    input_tokens=input_tokens,
                    error="input exceeds frozen model capacity",
                )
            )
            continue
        prompt = {
            "event_id": event_id,
            "documents_with_boundaries": text,
            "evidence_required": requires_evidence,
        }
        try:
            response = client.chat(
                system_prompt="Extract an Event Dossier without crossing Document boundaries.",
                user_prompt=json.dumps(prompt, ensure_ascii=False, sort_keys=True),
                response_format=None,
            )
            parsed = json.loads(str(getattr(response, "content", "") or "{}"))
            output.append(
                LongContextRunResult(
                    event_id=event_id,
                    status="success",
                    input_tokens=input_tokens,
                    raw_output=parsed,
                )
            )
        except Exception as exc:  # noqa: BLE001 - provider exceptions are untyped
            output.append(
                LongContextRunResult(
                    event_id=event_id,
                    status="model_error",
                    input_tokens=input_tokens,
                    error=str(exc),
                )
            )
    return output


def method_spec(method_id: MethodId) -> BaselineSpec:
    return next(row for row in METHOD_SPECS if row.method_id == method_id)


def build_comparison_manifest(
    protocol: FairnessProtocol,
    *,
    model_name: str,
    prompt_version: str,
    decoding_version: str,
    seed: int,
    output_root: str,
    token_budget: int = 0,
) -> ComparisonManifest:
    """Materialize all five frozen methods under one fairness protocol."""
    return ComparisonManifest(
        runs=[
            MethodRunManifest(
                method_id=method_id,
                protocol=protocol,
                model_name=model_name,
                prompt_version=prompt_version,
                decoding_version=decoding_version,
                seed=seed,
                output_path=f"{output_root}/{method_id}.json",
                token_budget=token_budget,
            )
            for method_id in METHOD_IDS
        ]
    )
