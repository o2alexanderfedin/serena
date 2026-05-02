"""Stage 1J T2 — ``_render_plugin_json`` emits boostvolt-shape plugin manifest."""

from __future__ import annotations

import json

from serena.refactoring.plugin_generator import _render_plugin_json


def test_render_plugin_json_for_rust(fake_strategy_rust) -> None:
    out = _render_plugin_json(fake_strategy_rust)
    data = json.loads(out)
    assert data["name"] == "o2-scalpel-rust"
    assert data["description"] == (
        "Scalpel refactor MCP server for Rust via rust-analyzer"
    )
    assert data["version"] == "1.0.5"
    assert data["author"]["name"] == "Alex Fedin & AI Hive®"
    assert data["author"]["email"] == "af@O2.services"
    assert data["author"]["url"] == "https://O2.services"
    assert data["license"] == "MIT"
    assert data["repository"].startswith("https://github.com")
    assert data["homepage"].startswith("https://github.com")


def test_render_plugin_json_is_deterministic(fake_strategy_rust) -> None:
    a = _render_plugin_json(fake_strategy_rust)
    b = _render_plugin_json(fake_strategy_rust)
    assert a == b
    assert a.endswith("\n")  # POSIX trailing newline


def test_render_plugin_json_for_python(fake_strategy_python) -> None:
    out = _render_plugin_json(fake_strategy_python)
    data = json.loads(out)
    assert data["name"] == "o2-scalpel-python"
    assert "Python" in data["description"]
    assert "pylsp" in data["description"]
