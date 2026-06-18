"""Validation tests for paper.yaml and ablation.yaml consistency.

Checks that both config files are loadable, internally consistent, and
compatible with the code-level ABLATION_SETTINGS in pipeline.py.
"""

import pytest

from episoa.config import load_config
from episoa.pipeline import ABLATION_SETTINGS


# ── helpers ──────────────────────────────────────────────────────────

REQUIRED_MODEL_KEYS = {
    "mode",
    "llm_mode",
    "provider",
    "llm_model",
    "model_name",
    "api_key_env",
    "temperature",
    "max_tokens",
    "timeout_seconds",
    "max_retries",
}

REQUIRED_DATA_KEYS = {
    "events_path",
    "evidence_path",
    "gold_tuples_path",
    "gold_event_chains_path",
    "annotation_sheet_path",
}

REQUIRED_OUTPUT_KEYS = {"runs_dir"}

REQUIRED_ABLATION_KEYS = {"method_version", "max_evidence_per_event", "evidence_selector"}
REQUIRED_EVIDENCE_SELECTOR_KEYS = {"mode"}

CONFIG_PATHS = ["configs/paper.yaml", "configs/ablation.yaml"]


# ── loadability ──────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("config_path", CONFIG_PATHS)
def test_config_loads(config_path: str) -> None:
    """Every production config file must load without error."""
    config = load_config(config_path)
    # Sanity-check that the returned object is a real PaperConfig
    assert config.run_id, f"{config_path}: run_id is empty"
    assert config.mode, f"{config_path}: mode is empty"


# ── required fields ──────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("config_path", CONFIG_PATHS)
def test_required_fields_present(config_path: str) -> None:
    """Verify that every config carries the top-level sections needed by the pipeline."""
    config = load_config(config_path)

    # Data block
    assert config.data, f"{config_path}: data section is empty"
    for key in REQUIRED_DATA_KEYS:
        assert key in config.data, f"{config_path}: missing data.{key}"

    # Model block
    assert config.model, f"{config_path}: model section is empty"
    for key in REQUIRED_MODEL_KEYS:
        assert key in config.model, f"{config_path}: missing model.{key}"

    # Output block
    assert config.output, f"{config_path}: output section is empty"
    for key in REQUIRED_OUTPUT_KEYS:
        assert key in config.output, f"{config_path}: missing output.{key}"

    # Runtime block
    assert config.runtime, f"{config_path}: runtime section is empty"

    # Ablation block
    assert config.ablation, f"{config_path}: ablation section is empty"
    for key in REQUIRED_ABLATION_KEYS:
        assert key in config.ablation, f"{config_path}: missing ablation.{key}"
    # Evidence selector inside ablation
    sel = config.ablation.get("evidence_selector", {})
    for key in REQUIRED_EVIDENCE_SELECTOR_KEYS:
        assert key in sel, f"{config_path}: missing ablation.evidence_selector.{key}"


# ── mode-specific 👇 ────────────────────────────────────────────────


@pytest.mark.integration
def test_paper_config_mode() -> None:
    """paper.yaml must declare mode: paper."""
    config = load_config("configs/paper.yaml")
    assert config.mode == "paper", f"Expected mode='paper', got {config.mode!r}"


@pytest.mark.integration
def test_ablation_config_mode() -> None:
    """ablation.yaml must declare mode: ablation."""
    config = load_config("configs/ablation.yaml")
    assert config.mode == "ablation", f"Expected mode='ablation', got {config.mode!r}"


@pytest.mark.integration
def test_ablation_config_has_settings_list() -> None:
    """ablation.yaml must define an ablation.settings list (paper.yaml may omit it)."""
    config = load_config("configs/ablation.yaml")
    settings = config.ablation.get("settings", [])
    assert isinstance(settings, list), "ablation.settings is not a list"
    assert len(settings) >= 1, "ablation.settings is empty"


# ── model consistency ───────────────────────────────────────────────-


@pytest.mark.integration
def test_llm_model_consistent() -> None:
    """paper.yaml and ablation.yaml must agree on llm_model and model_name."""
    paper = load_config("configs/paper.yaml")
    ablation = load_config("configs/ablation.yaml")

    assert paper.model["llm_model"] == ablation.model["llm_model"], (
        f"llm_model mismatch: paper={paper.model['llm_model']!r} "
        f"vs ablation={ablation.model['llm_model']!r}"
    )
    assert paper.model["model_name"] == ablation.model["model_name"], (
        f"model_name mismatch: paper={paper.model['model_name']!r} "
        f"vs ablation={ablation.model['model_name']!r}"
    )
    assert paper.model["provider"] == ablation.model["provider"], (
        f"provider mismatch: paper={paper.model['provider']!r} "
        f"vs ablation={ablation.model['provider']!r}"
    )


@pytest.mark.integration
def test_temperature_consistent() -> None:
    """Both configs should use the same temperature for reproducibility."""
    paper = load_config("configs/paper.yaml")
    ablation = load_config("configs/ablation.yaml")
    assert paper.model["temperature"] == ablation.model["temperature"], (
        f"temperature mismatch: paper={paper.model['temperature']} "
        f"vs ablation={ablation.model['temperature']}"
    )


# ── ablation settings vs code ───────────────────────────────────────-


@pytest.mark.integration
def test_ablation_settings_match_code() -> None:
    """Every setting name in ablation.yaml must exist in ABLATION_SETTINGS in pipeline.py."""
    config = load_config("configs/ablation.yaml")
    yaml_settings: list[str] = config.ablation.get("settings", [])
    known_settings: set[str] = set(ABLATION_SETTINGS.keys())

    unknown = [s for s in yaml_settings if s not in known_settings]
    assert not unknown, (
        f"Ablation setting(s) in YAML not found in ABLATION_SETTINGS: {unknown}\n"
        f"Known settings: {sorted(known_settings)}"
    )


@pytest.mark.integration
def test_paper_has_no_settings_list() -> None:
    """paper.yaml should NOT define an ablation.settings list (only ablation.yaml does)."""
    config = load_config("configs/paper.yaml")
    settings = config.ablation.get("settings")
    if settings is not None:
        pytest.fail(f"paper.yaml unexpectedly contains ablation.settings={settings}")


# ── API key safety ───────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("config_path", CONFIG_PATHS)
def test_no_api_key_leaked(config_path: str) -> None:
    """Configs must use api_key_env, not hard-coded api_key values.

    An empty-string or absent api_key is acceptable — the real credential
    comes from the environment variable named by api_key_env.
    """
    config = load_config(config_path)

    model_api_key = config.model.get("api_key")
    assert not model_api_key, (
        f"{config_path}: model.api_key should be empty or absent; "
        f"got {model_api_key!r}. Use api_key_env instead."
    )

    search_api_key = config.search.get("api_key")
    assert not search_api_key, (
        f"{config_path}: search.api_key should be empty or absent; "
        f"got {search_api_key!r}. Use api_key_env instead."
    )
