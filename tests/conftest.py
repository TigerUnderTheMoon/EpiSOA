"""Pytest defaults that keep the suite deterministic and mock-only."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Force all default pytest runs into mock mode."""
    os.environ.setdefault("EPISOA_TESTING", "1")
    os.environ.setdefault("EPISOA_EMBEDDING_MODE", "mock")
    os.environ.setdefault("EPISOA_LLM_MODE", "mock")
    os.environ.setdefault("EPISOA_BROWSER_MODE", "mock")
    os.environ.setdefault("EPISOA_SEARCH_MODE", "mock")
    os.environ.setdefault("EPISOA_GRAPH_STORE", "networkx")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Treat unmarked tests as unit tests for marker-based selection."""
    excluded_markers = {"integration", "slow", "real_model", "browser"}
    for item in items:
        item_markers = {marker.name for marker in item.iter_markers()}
        if not item_markers & excluded_markers and "unit" not in item_markers:
            item.add_marker(pytest.mark.unit)
