"""Configuration loading for the EpiSOA paper workflow."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PaperConfig:
    run_id: str
    mode: str
    data: dict[str, str]
    output: dict[str, str]
    model: dict[str, Any]
    search: dict[str, Any]
    retrieval: dict[str, Any]
    verifier: dict[str, Any]
    ablation: dict[str, Any]

    @property
    def run_dir(self) -> Path:
        return Path(self.output.get("runs_dir", "outputs/runs")) / self.run_id


def load_config(path: str | Path) -> PaperConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return PaperConfig(
        run_id=str(raw.get("run_id", "paper-run")),
        mode=str(raw.get("mode", "paper")),
        data=dict(raw.get("data", {})),
        output=dict(raw.get("output", {"runs_dir": "outputs/runs"})),
        model=dict(raw.get("model", {})),
        search=dict(raw.get("search", {})),
        retrieval=dict(raw.get("retrieval", {"top_k": 5})),
        verifier=dict(raw.get("verifier", {"threshold": 0.75})),
        ablation=dict(raw.get("ablation", {})),
    )


def resolve_api_config(raw: dict[str, Any], *, label: str) -> dict[str, Any]:
    """Resolve API key and base URL with YAML-first precedence."""
    api_key, api_key_source = _resolve_value(raw, "api_key", "api_key_env")
    base_url, base_url_source = _resolve_value(raw, "base_url", "base_url_env")
    if not api_key:
        raise RuntimeError(
            f"{label} api_key is missing. Set api_key in YAML or set the environment variable named by api_key_env."
        )
    if not base_url:
        raise RuntimeError(
            f"{label} base_url is missing. Set base_url in YAML or set the environment variable named by base_url_env."
        )
    return {
        "api_key": api_key,
        "api_key_source": api_key_source,
        "api_key_masked": mask_secret(api_key),
        "base_url": base_url,
        "base_url_source": base_url_source,
    }


def api_config_status(config: PaperConfig) -> dict[str, Any]:
    """Return non-secret API configuration status for logging/status output."""
    status: dict[str, Any] = {}
    for label, raw in (("model", config.model), ("search", config.search)):
        if not raw:
            status[label] = {"configured": False, "error": f"{label} config is not present"}
            continue
        try:
            resolved = resolve_api_config(raw, label=label)
            status[label] = {
                "configured": True,
                "api_key_source": resolved["api_key_source"],
                "api_key_masked": resolved["api_key_masked"],
                "base_url_source": resolved["base_url_source"],
                "base_url": resolved["base_url"],
            }
        except RuntimeError as exc:
            status[label] = {"configured": False, "error": str(exc)}
    return status


def print_api_config_status(config: PaperConfig) -> None:
    """Print safe API key/base URL source information."""
    status = api_config_status(config)
    for label, item in status.items():
        if item.get("configured"):
            print(
                f"{label}: api_key={item['api_key_source']}:{item['api_key_masked']} "
                f"base_url={item['base_url_source']}:{item['base_url']}"
            )
        else:
            print(f"{label}: {item['error']}")


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return value[:1] + "***" + value[-1:]
    return value[:4] + "***" + value[-4:]


def _resolve_value(raw: dict[str, Any], direct_key: str, env_key: str) -> tuple[str | None, str]:
    direct_value = raw.get(direct_key)
    if isinstance(direct_value, str) and direct_value.strip() and not _is_placeholder(direct_value):
        return direct_value.strip(), "yaml"
    env_name = raw.get(env_key)
    if isinstance(env_name, str) and env_name.strip():
        env_value = os.getenv(env_name.strip())
        if env_value and not _is_placeholder(env_value):
            return env_value, f"env:{env_name.strip()}"
    return None, "missing"


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("your-") or "your-" in lowered or "your_" in lowered
