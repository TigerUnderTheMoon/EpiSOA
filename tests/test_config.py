import os

import pytest

from episoa.config import api_config_status, load_config, mask_secret, resolve_api_config


def test_resolve_api_config_prefers_yaml_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")

    resolved = resolve_api_config(
        {
            "api_key": "yaml-key",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://yaml.example/v1",
            "base_url_env": "OPENAI_BASE_URL",
        },
        label="model",
    )

    assert resolved["api_key"] == "yaml-key"
    assert resolved["api_key_source"] == "yaml"
    assert resolved["base_url"] == "https://yaml.example/v1"
    assert resolved["base_url_source"] == "yaml"


def test_resolve_api_config_uses_env_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")

    resolved = resolve_api_config(
        {
            "api_key": "",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "",
            "base_url_env": "OPENAI_BASE_URL",
        },
        label="model",
    )

    assert resolved["api_key"] == "env-key"
    assert resolved["api_key_source"] == "env:OPENAI_API_KEY"
    assert resolved["base_url"] == "https://env.example/v1"
    assert resolved["base_url_source"] == "env:OPENAI_BASE_URL"


def test_resolve_api_config_reports_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="api_key is missing"):
        resolve_api_config({"api_key_env": "OPENAI_API_KEY", "base_url": "https://base.example/v1"}, label="model")


def test_mask_secret_only_shows_edges():
    assert mask_secret("dummy-api-key-abcd") == "dumm***abcd"


def test_paper_config_status_does_not_expose_full_key(tmp_path):
    config_path = tmp_path / "paper.yaml"
    config_path.write_text(
        """
run_id: test
mode: paper
data: {}
output: {}
model:
  api_key: dummy-api-key-abcd
  api_key_env: OPENAI_API_KEY
  base_url: https://yaml.example/v1
search:
  api_key: search-123456
  api_key_env: SEARCH_API_KEY
  base_url: https://search.example/v1
""",
        encoding="utf-8",
    )

    status = api_config_status(load_config(config_path))

    assert status["model"]["api_key_masked"] == "dumm***abcd"
    assert "dummy-api-key-abcd" not in str(status)
