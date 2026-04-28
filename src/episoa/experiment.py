"""Experiment run context and unified logging utilities."""

from __future__ import annotations

import logging
import json
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


LOGGER_NAME = "episoa"


@dataclass(frozen=True)
class RunContext:
    """Filesystem layout for one EpiSOA experiment run."""

    run_id: str
    run_dir: Path
    config_path: Path
    predictions_path: Path
    metrics_path: Path
    log_path: Path
    prompts_dir: Path


def make_run_id(run_name: str | None = None) -> str:
    """Create a stable, filesystem-safe run ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not run_name:
        return timestamp
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_name.strip()).strip("-").lower()
    return f"{timestamp}-{slug}" if slug else timestamp


def create_run_context(run_name: str | None = None, output_root: str | Path = "outputs/runs") -> RunContext:
    """Create directories and file paths for a run."""
    run_id = make_run_id(run_name)
    run_dir = Path(output_root) / run_id
    prompts_dir = run_dir / "prompts_used"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id=run_id,
        run_dir=run_dir,
        config_path=run_dir / "config.yaml",
        predictions_path=run_dir / "predictions.jsonl",
        metrics_path=run_dir / "metrics.json",
        log_path=run_dir / "run.log",
        prompts_dir=prompts_dir,
    )


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger under the unified EpiSOA namespace."""
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


def configure_logging(log_path: str | Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure console and optional file logging for all EpiSOA modules."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    logger.addHandler(stream_handler)

    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    return logger


def save_config_snapshot(config: dict[str, Any], path: str | Path) -> None:
    """Persist the effective run config."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(config, file, sort_keys=False, allow_unicode=True)


def set_random_seed(seed: int) -> None:
    """Fix supported random seeds for reproducible runs."""
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:
        pass


def run_metadata_from_config(config: dict[str, Any], seed: int) -> dict[str, Any]:
    """Extract reproducibility-critical metadata from a run config."""
    pipeline = config.get("pipeline", {})
    llm = config.get("llm", {})
    verifier = config.get("verifier", {})
    return {
        "seed": seed,
        "model_name": llm.get("model", "mock-attribution"),
        "llm_mode": llm.get("mode", "mock"),
        "prompt_version": llm.get("prompt_version", "v0"),
        "top_k": pipeline.get("top_k_evidence", pipeline.get("top_k", 5)),
        "path_depth": pipeline.get("eventrag_depth", pipeline.get("path_depth", 2)),
        "verifier_threshold": verifier.get("threshold", 0.75),
    }


def write_run_readme(config: dict[str, Any], run_context: RunContext) -> None:
    """Write a human-readable README.md describing the experiment run."""
    metadata = config.get("reproducibility", {})
    metrics = _read_json_if_exists(run_context.metrics_path)
    prompt_files = sorted(path.name for path in run_context.prompts_dir.glob("*"))

    lines = [
        f"# EpiSOA Run `{run_context.run_id}`",
        "",
        "## Artifacts",
        "",
        f"- Config: `config.yaml`",
        f"- Predictions: `predictions.jsonl`",
        f"- Metrics: `metrics.json`",
        f"- Log: `run.log`",
        f"- Prompts: `prompts_used/` ({len(prompt_files)} file(s))",
        "",
        "## Reproducibility",
        "",
        f"- Random seed: `{metadata.get('seed')}`",
        f"- LLM mode: `{metadata.get('llm_mode')}`",
        f"- Model name: `{metadata.get('model_name')}`",
        f"- Prompt version: `{metadata.get('prompt_version')}`",
        f"- top_k: `{metadata.get('top_k')}`",
        f"- path_depth: `{metadata.get('path_depth')}`",
        f"- verifier_threshold: `{metadata.get('verifier_threshold')}`",
        "",
        "## Results",
        "",
    ]
    if metrics:
        for key, value in metrics.items():
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- Metrics were not computed for this run.")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "This README is generated automatically from the effective run config and output artifacts.",
            "",
        ]
    )
    (run_context.run_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
