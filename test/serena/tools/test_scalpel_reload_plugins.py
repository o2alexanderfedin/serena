"""Stream 5 / Leaf 03 Task 3 — ``ScalpelReloadPluginsTool`` tests.

These tests bypass the full ``Tool.apply_ex`` lifecycle (it requires an
agent + active project) and call ``apply`` directly; the cross-MCP
boundary contract is asserted separately by the discovery test in
:mod:`test/serena/tools/test_scalpel_reload_plugins_registration`
(Task 4 — registration smoke).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from serena.plugins.registry import PluginRegistry
from serena.tools.scalpel_primitives import ScalpelReloadPluginsTool
from serena.tools.scalpel_runtime import ScalpelRuntime


def _make_plugin(plugin_dir: Path, *, id_: str) -> Path:
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "plugin.json"
    manifest_path.write_text(
        json.dumps({
            "name": id_,
            "description": "Test plugin",
            "version": "1.0.0",
            "author": {"name": "AI Hive(R)"},
            "license": "MIT",
            "repository": "https://example.com/repo",
            "homepage": "https://example.com/repo",
        }),
        encoding="utf-8",
    )
    return manifest_path


def _build_tool(registry: PluginRegistry) -> ScalpelReloadPluginsTool:
    """Inject a ``PluginRegistry`` into the ScalpelRuntime singleton.

    ``Tool.__init__`` requires an agent — we hand it a ``MagicMock``
    because ``apply`` only touches ``ScalpelRuntime.instance().plugin_registry()``.
    """
    runtime = ScalpelRuntime.instance()
    runtime.set_plugin_registry_for_testing(registry)
    return ScalpelReloadPluginsTool(agent=MagicMock(name="SerenaAgent"))


def test_reload_tool_returns_clean_report_for_new_plugin(tmp_path: Path) -> None:
    ScalpelRuntime.reset_for_testing()
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _make_plugin(plugins_dir / "rust", id_="rust")
    registry = PluginRegistry(plugins_dir)
    tool = _build_tool(registry)

    payload = json.loads(tool.apply())

    assert payload["is_clean"] is True
    assert payload["added"] == ["rust"]
    assert payload["removed"] == []
    ScalpelRuntime.reset_for_testing()


def test_reload_tool_marks_unchanged_on_second_call(tmp_path: Path) -> None:
    ScalpelRuntime.reset_for_testing()
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _make_plugin(plugins_dir / "rust", id_="rust")
    registry = PluginRegistry(plugins_dir)
    tool = _build_tool(registry)

    tool.apply()  # first reload — added: ["rust"]
    second = json.loads(tool.apply())

    assert second["unchanged"] == ["rust"]
    assert second["added"] == []
    assert second["is_clean"] is True
    ScalpelRuntime.reset_for_testing()


def test_reload_tool_surfaces_errors(tmp_path: Path) -> None:
    ScalpelRuntime.reset_for_testing()
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    bad_dir = plugins_dir / "broken" / ".claude-plugin"
    bad_dir.mkdir(parents=True)
    (bad_dir / "plugin.json").write_text("not valid json", encoding="utf-8")
    registry = PluginRegistry(plugins_dir)
    tool = _build_tool(registry)

    payload = json.loads(tool.apply())

    assert payload["is_clean"] is False
    assert any(name == "broken" for name, _ in payload["errors"])
    ScalpelRuntime.reset_for_testing()


def test_reload_tool_returns_json_string(tmp_path: Path) -> None:
    """``apply`` returns a JSON string (matches scalpel_primitives idiom)."""
    ScalpelRuntime.reset_for_testing()
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    registry = PluginRegistry(plugins_dir)
    tool = _build_tool(registry)

    out = tool.apply()
    assert isinstance(out, str)
    parsed = json.loads(out)  # well-formed JSON
    assert isinstance(parsed, dict)
    assert "added" in parsed
    ScalpelRuntime.reset_for_testing()
