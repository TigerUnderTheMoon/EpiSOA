"""Unified configuration schema for EpiSOA experiments."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


Mode = Literal["mock", "real", "ablation"]
LLMMode = Literal["mock", "real"]

ABLATION_DISABLE_FIELDS = (
    "disable_fsm",
    "disable_diversity",
    "disable_graph",
    "disable_event_chain",
    "disable_verifier",
    "disable_temporal_edges",
    "disable_stakeholder_constraint",
)


class DataConfig(BaseModel):
    """Dataset and gold annotation paths."""

    model_config = ConfigDict(extra="forbid")

    evidence_path: str = Field(..., min_length=1)
    gold_path: str = Field(..., min_length=1)
    event_query_path: str = Field(..., min_length=1)
    dataset_name: str = Field(..., min_length=1)
    gold_event_chains_path: str | None = None


class ModelConfig(BaseModel):
    """LLM and retrieval model identifiers."""

    model_config = ConfigDict(extra="forbid")

    mode: LLMMode | None = None
    llm_mode: LLMMode = "mock"
    llm_model: str = Field(..., min_length=1)
    embedding_model: str = Field(..., min_length=1)
    reranker_model: str = Field(..., min_length=1)
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "http://localhost:8000/v1"
    timeout_seconds: int = 30
    max_retries: int = 2
    temperature: float = 0.0
    prompt_version: str = "v0"

    @model_validator(mode="after")
    def sync_mode_aliases(self) -> "ModelConfig":
        if self.mode is None:
            self.mode = self.llm_mode
        else:
            self.llm_mode = self.mode
        return self


class RetrievalConfig(BaseModel):
    """Evidence retrieval parameters."""

    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(..., ge=1)
    candidate_k: int = Field(..., ge=1)
    use_diversity: bool = True
    embedding_mode: str = "mock"
    reranker_mode: str = "mock"
    cache_dir: str = Field(..., min_length=1)


class GraphConfig(BaseModel):
    """Evidence graph settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class EventChainConfig(BaseModel):
    """Event-chain retrieval settings."""

    model_config = ConfigDict(extra="forbid")

    max_depth: int = Field(..., ge=1, le=3)
    top_k: int = Field(..., ge=1)
    enabled: bool = True


class VerifierConfig(BaseModel):
    """Evidence verifier settings."""

    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(..., ge=0.0, le=1.0)
    enabled: bool = True


class AblationConfig(BaseModel):
    """Ablation switches expressed as disable flags."""

    model_config = ConfigDict(extra="forbid")

    disable_fsm: bool = False
    disable_diversity: bool = False
    disable_graph: bool = False
    disable_event_chain: bool = False
    disable_verifier: bool = False
    disable_temporal_edges: bool = False
    disable_stakeholder_constraint: bool = False

    def disabled_modules(self) -> list[str]:
        """Return enabled ablation switches using their config field names."""
        return [name for name in ABLATION_DISABLE_FIELDS if bool(getattr(self, name))]


class OutputConfig(BaseModel):
    """Output directory settings."""

    model_config = ConfigDict(extra="forbid")

    run_dir: str = Field(..., min_length=1)


class ExperimentConfig(BaseModel):
    """Top-level EpiSOA experiment configuration."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    run_id: str = Field(..., min_length=1)
    mode: Mode = "mock"
    data: DataConfig
    output: OutputConfig
    model: ModelConfig
    retrieval: RetrievalConfig
    graph: GraphConfig
    event_chain: EventChainConfig
    verifier: VerifierConfig
    ablation: AblationConfig = Field(default_factory=AblationConfig)
    methods: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ablation_settings: dict[str, AblationConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def resolve_output_run_dir(self) -> "ExperimentConfig":
        self.output.run_dir = self.output.run_dir.format(run_id=self.run_id)
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExperimentConfig":
        raw = load_yaml(path)
        if "data" not in raw:
            raw = legacy_to_unified(raw, path)
        return cls.model_validate(raw)

    def to_runtime_dict(self) -> dict[str, Any]:
        """Return compatibility keys consumed by existing pipeline code."""
        use_graph = self.graph.enabled and not self.ablation.disable_graph
        use_event_chain = self.event_chain.enabled and not self.ablation.disable_event_chain
        use_verifier = self.verifier.enabled and not self.ablation.disable_verifier
        use_diversity = self.retrieval.use_diversity and not self.ablation.disable_diversity
        use_temporal = not self.ablation.disable_temporal_edges
        return {
            "seed": self.seed,
            "run_id": self.run_id,
            "mode": self.mode,
            "data": self.data.model_dump(),
            "output": self.output.model_dump(),
            "run": {
                "name": self.run_id,
                "run_id": self.run_id,
                "seed": self.seed,
                "output_dir": self.output.run_dir,
            },
            "dataset": {
                "event_file": Path(self.data.event_query_path).name,
                "evidence_file": Path(self.data.evidence_path).name,
                "gold_tuple_file": Path(self.data.gold_path).name,
                "gold_event_chain_file": Path(self.data.gold_event_chains_path or "gold_event_chains.jsonl").name,
            },
            "pipeline": {
                "top_k_evidence": self.retrieval.top_k,
                "top_k": self.retrieval.top_k,
                "candidate_k": self.retrieval.candidate_k,
                "eventrag_depth": self.event_chain.max_depth,
                "eventrag_top_k": self.event_chain.top_k,
                "output_path": str(Path(self.output.run_dir) / "predictions.jsonl"),
            },
            "collector": {
                "collection_mode": "mock" if self.mode == "mock" else "semireal_search",
                "mock_coverage_scenario": "covered",
                "max_queries_per_event": 8,
                "max_pages_per_query": 5,
                "max_evidence_per_event": 80,
                "recursion_limit": 30,
            },
            "llm": {
                "llm_mode": self.model.llm_mode,
                "mode": self.model.llm_mode,
                "model": self.model.llm_model,
                "base_url": self.model.base_url,
                "api_key_env": self.model.api_key_env,
                "timeout_seconds": self.model.timeout_seconds,
                "max_retries": self.model.max_retries,
                "temperature": self.model.temperature,
                "prompt_version": self.model.prompt_version,
                "local_command": None,
            },
            "retrieval": {
                "top_k": self.retrieval.top_k,
                "candidate_k": self.retrieval.candidate_k,
                "use_diversity": use_diversity,
                "embedding_mode": self.retrieval.embedding_mode,
                "embedding_model_name": self.model.embedding_model,
                "reranker_mode": self.retrieval.reranker_mode,
                "reranker_model_name": self.model.reranker_model,
                "cache_dir": self.retrieval.cache_dir,
            },
            "graph": {"enabled": use_graph},
            "event_chain": {
                "max_depth": self.event_chain.max_depth,
                "top_k": self.event_chain.top_k,
                "enabled": use_event_chain,
            },
            "verifier": {"threshold": self.verifier.threshold, "enabled": use_verifier},
            "evaluation": {
                "gold_path": self.data.gold_path,
                "gold_event_chains_path": self.data.gold_event_chains_path,
                "k": self.retrieval.top_k,
            },
            "ablation": {
                "use_fsm_collector": not self.ablation.disable_fsm,
                "use_feedback_transitions": True,
                "use_diversity_retriever": use_diversity,
                "use_evidence_graph": use_graph,
                "use_event_chain_retriever": use_event_chain,
                "use_verifier": use_verifier,
                "use_temporal_information": use_temporal,
                "disable_stakeholder_constraint": self.ablation.disable_stakeholder_constraint,
            },
            "methods": self.methods,
            "settings": {
                name: _ablation_to_runtime(setting)
                for name, setting in self.ablation_settings.items()
            },
        }

    def disabled_modules(self) -> list[str]:
        """Return the module switches disabled for this run."""
        return self.ablation.disabled_modules()

    def validate_mode_requirements(self) -> None:
        """Fail fast when a run mode would silently use the wrong backend."""
        if self.mode == "real":
            api_key_env = self.model.api_key_env
            if not os.getenv(api_key_env):
                raise RuntimeError(
                    f"real mode requires API key environment variable {api_key_env} for LLMClient; "
                    "set it before running. EpiSOA will not fall back to mock mode."
                )
            errors: list[str] = []
            if self.model.llm_mode != "real":
                errors.append("model.mode/model.llm_mode must be real")
            if self.retrieval.embedding_mode != "sentence_transformers":
                errors.append("retrieval.embedding_mode must be sentence_transformers")
            if self.retrieval.reranker_mode != "bge_reranker":
                errors.append("retrieval.reranker_mode must be bge_reranker")
            if errors:
                detail = "; ".join(errors)
                raise RuntimeError(f"real mode requires real clients only: {detail}")


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    return ExperimentConfig.from_yaml(path)


def load_runtime_config(path: str | Path) -> dict[str, Any]:
    return load_experiment_config(path).to_runtime_dict()


def legacy_to_unified(raw: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    """Best-effort adapter for older config snippets used in tests."""
    dataset = raw.get("dataset", {})
    defaults = raw.get("defaults", {})
    pipeline = raw.get("pipeline", {})
    llm = raw.get("llm", {})
    retrieval = raw.get("retrieval", {})
    verifier = raw.get("verifier", {})
    run = raw.get("run", {})
    dataset_name = str(run.get("name") or defaults.get("dataset_name") or "pubevent_soa_lite")
    dataset_root = Path("data") / dataset_name
    event_file = dataset.get("event_file") or Path(defaults.get("event_path", dataset_root / "events.jsonl")).name
    evidence_file = dataset.get("evidence_file") or Path(defaults.get("evidence_path", dataset_root / "evidence.jsonl")).name
    gold_file = dataset.get("gold_tuple_file") or Path(defaults.get("gold_path", dataset_root / "gold_tuples.jsonl")).name
    chain_file = dataset.get("gold_event_chain_file", "gold_event_chains.jsonl")
    return {
        "seed": int(raw.get("seed", raw.get("reproducibility", {}).get("seed", run.get("seed", 13)))),
        "run_id": str(run.get("run_id") or run.get("name") or Path(path or "config").stem),
        "mode": "ablation" if "ablation" in Path(path or "").stem else ("real" if llm.get("llm_mode") == "real" else "mock"),
        "data": {
            "evidence_path": str(dataset_root / evidence_file),
            "gold_path": str(dataset_root / gold_file),
            "event_query_path": str(dataset_root / event_file),
            "dataset_name": dataset_name,
            "gold_event_chains_path": str(dataset_root / chain_file),
        },
        "output": {"run_dir": str(run.get("output_dir") or defaults.get("output_dir") or "outputs/runs/{run_id}")},
        "model": {
            "llm_mode": "real" if llm.get("llm_mode") in {"real", "openai_compatible"} else "mock",
            "llm_model": str(llm.get("model", "mock-attribution")),
            "embedding_model": str(retrieval.get("embedding_model_name", "mock-embedding")),
            "reranker_model": str(retrieval.get("reranker_model_name", "mock-reranker")),
            "api_key_env": str(llm.get("api_key_env", "OPENAI_API_KEY")),
            "base_url": str(llm.get("base_url", "http://localhost:8000/v1")),
            "timeout_seconds": int(llm.get("timeout_seconds", 30)),
            "max_retries": int(llm.get("max_retries", 2)),
            "temperature": float(llm.get("temperature", 0)),
            "prompt_version": str(llm.get("prompt_version", "v0")),
        },
        "retrieval": {
            "top_k": int(pipeline.get("top_k_evidence", pipeline.get("top_k", retrieval.get("top_k", 5)))),
            "candidate_k": int(retrieval.get("candidate_k", pipeline.get("top_k_evidence", 5))),
            "use_diversity": True,
            "embedding_mode": str(retrieval.get("embedding_mode", "mock")),
            "reranker_mode": str(retrieval.get("reranker_mode", "mock")),
            "cache_dir": str(retrieval.get("cache_dir", "outputs/cache/embeddings")),
        },
        "graph": {"enabled": bool(raw.get("graph", {}).get("enabled", True))},
        "event_chain": {
            "max_depth": int(pipeline.get("eventrag_depth", 2)),
            "top_k": int(pipeline.get("eventrag_top_k", 3)),
            "enabled": bool(raw.get("event_chain", {}).get("enabled", True)),
        },
        "verifier": {
            "threshold": float(verifier.get("threshold", 0.75)),
            "enabled": bool(verifier.get("enabled", True)),
        },
        "ablation": _legacy_ablation_to_disable(raw.get("ablation", {})),
        "methods": raw.get("methods", raw.get("baselines", {})),
        "ablation_settings": {
            name: AblationConfig.model_validate(_legacy_ablation_to_disable(value)).model_dump()
            for name, value in raw.get("settings", {}).items()
        },
    }


def _legacy_ablation_to_disable(raw: dict[str, Any]) -> dict[str, bool]:
    return {
        "disable_fsm": not bool(raw.get("use_fsm_collector", True)),
        "disable_diversity": not bool(raw.get("use_diversity_retriever", True)),
        "disable_graph": not bool(raw.get("use_evidence_graph", True)),
        "disable_event_chain": not bool(raw.get("use_event_chain_retriever", True)),
        "disable_verifier": not bool(raw.get("use_verifier", True)),
        "disable_temporal_edges": not bool(raw.get("use_temporal_information", True)),
        "disable_stakeholder_constraint": bool(raw.get("disable_stakeholder_constraint", False)),
    }


def _ablation_to_runtime(config: AblationConfig) -> dict[str, bool]:
    return {
        "use_fsm_collector": not config.disable_fsm,
        "use_feedback_transitions": True,
        "use_diversity_retriever": not config.disable_diversity,
        "use_evidence_graph": not config.disable_graph,
        "use_event_chain_retriever": not config.disable_event_chain,
        "use_verifier": not config.disable_verifier,
        "use_temporal_information": not config.disable_temporal_edges,
        "disable_stakeholder_constraint": config.disable_stakeholder_constraint,
    }
