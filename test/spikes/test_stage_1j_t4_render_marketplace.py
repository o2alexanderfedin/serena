"""Stage 1J T4 — ``_render_marketplace_json`` aggregates language plugins."""

from __future__ import annotations

import json

from serena.refactoring.plugin_generator import _render_marketplace_json


def test_marketplace_includes_all_strategies(
    fake_strategy_rust, fake_strategy_python
) -> None:
    out = _render_marketplace_json([fake_strategy_python, fake_strategy_rust])
    data = json.loads(out)
    assert data["$schema"].endswith("marketplace.schema.json")
    assert data["name"] == "o2-scalpel"
    assert data["owner"]["name"] == "AI Hive(R)"
    names = [p["name"] for p in data["plugins"]]
    assert names == ["o2-scalpel-python", "o2-scalpel-rust"]  # sorted by language


def test_marketplace_sources_use_relative_paths(fake_strategy_rust) -> None:
    out = _render_marketplace_json([fake_strategy_rust])
    data = json.loads(out)
    assert data["plugins"][0]["source"] == "./o2-scalpel-rust"


def test_marketplace_is_deterministic(
    fake_strategy_rust, fake_strategy_python
) -> None:
    a = _render_marketplace_json([fake_strategy_rust, fake_strategy_python])
    b = _render_marketplace_json([fake_strategy_python, fake_strategy_rust])
    assert a == b
    assert a.endswith("\n")
