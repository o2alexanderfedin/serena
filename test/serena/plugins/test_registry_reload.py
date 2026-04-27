"""Stream 5 / Leaf 03 Task 2 — ``PluginRegistry.reload()`` tests."""

from __future__ import annotations

import json
from pathlib import Path

from serena.plugins.registry import PluginRegistry


def _make_plugin(
    plugin_dir: Path,
    *,
    id_: str,
    version: str = "1.0.0",
    description: str = "Test plugin",
) -> Path:
    """Render a minimal valid boostvolt-shape ``plugin.json`` tree.

    Returns the manifest path. Mirrors the layout the Stage 1J generator
    emits at the parent ``o2-scalpel-<language>/.claude-plugin/plugin.json``
    location.
    """
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "plugin.json"
    manifest_path.write_text(
        json.dumps({
            "name": id_,
            "description": description,
            "version": version,
            "author": {"name": "AI Hive(R)"},
            "license": "MIT",
            "repository": "https://example.com/repo",
            "homepage": "https://example.com/repo",
        }),
        encoding="utf-8",
    )
    return manifest_path


def test_registry_reload_picks_up_new_plugin(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    reg = PluginRegistry(plugins_dir)
    assert reg.list_ids() == []

    _make_plugin(plugins_dir / "rust", id_="rust")
    report = reg.reload()

    assert report.added == ("rust",)
    assert report.removed == ()
    assert report.unchanged == ()
    assert report.errors == ()
    assert report.is_clean is True
    assert reg.list_ids() == ["rust"]


def test_registry_reload_detects_removal(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_dir = plugins_dir / "rust"
    _make_plugin(plugin_dir, id_="rust")
    reg = PluginRegistry(plugins_dir)
    reg.reload()
    assert reg.list_ids() == ["rust"]

    # Drop the manifest, reload, expect the plugin to disappear.
    (plugin_dir / ".claude-plugin" / "plugin.json").unlink()
    report = reg.reload()
    assert report.added == ()
    assert report.removed == ("rust",)
    assert report.unchanged == ()
    assert reg.list_ids() == []


def test_registry_reload_marks_unchanged(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _make_plugin(plugins_dir / "rust", id_="rust")
    _make_plugin(plugins_dir / "python", id_="python")
    reg = PluginRegistry(plugins_dir)
    reg.reload()

    # Add one more, reload, expect unchanged for the original two.
    _make_plugin(plugins_dir / "kotlin", id_="kotlin")
    report = reg.reload()
    assert report.added == ("kotlin",)
    assert report.unchanged == ("python", "rust")
    assert report.removed == ()


def test_registry_reload_surfaces_validation_error_per_plugin(
    tmp_path: Path,
) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _make_plugin(plugins_dir / "rust", id_="rust")
    # Sibling plugin with a malformed manifest — empty name violates
    # PluginManifest's regex.
    bad_dir = plugins_dir / "broken" / ".claude-plugin"
    bad_dir.mkdir(parents=True)
    (bad_dir / "plugin.json").write_text(
        json.dumps({
            "name": "",
            "description": "x",
            "version": "1.0.0",
            "author": {"name": "AI Hive(R)"},
            "license": "MIT",
            "repository": "https://example.com/repo",
            "homepage": "https://example.com/repo",
        }),
        encoding="utf-8",
    )
    reg = PluginRegistry(plugins_dir)
    report = reg.reload()

    # Healthy sibling still loads.
    assert "rust" in report.added
    assert reg.list_ids() == ["rust"]
    # Broken sibling surfaces as a per-plugin error.
    assert report.is_clean is False
    assert any(name == "broken" for name, _ in report.errors)


def test_registry_reload_skips_directories_without_manifest(
    tmp_path: Path,
) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "scratch").mkdir()  # bare dir — should be skipped silently
    _make_plugin(plugins_dir / "rust", id_="rust")
    reg = PluginRegistry(plugins_dir)
    report = reg.reload()
    assert report.added == ("rust",)
    assert report.errors == ()


def test_registry_reload_tolerates_missing_plugins_dir(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "does_not_exist"
    reg = PluginRegistry(plugins_dir)
    report = reg.reload()
    assert report.added == ()
    assert report.removed == ()
    assert report.errors == ()
    assert report.is_clean is True


def test_registry_reload_strips_generator_metadata(tmp_path: Path) -> None:
    """Stage 1J stamps a private ``_generator`` field into plugin.json.

    PluginManifest forbids extras, so the registry must strip private
    keys before validation — otherwise every generator-emitted plugin
    would surface as a validation error.
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin_dir = plugins_dir / "rust" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({
            "_generator": "Generated by o2-scalpel-newplugin",
            "name": "rust",
            "description": "Test plugin",
            "version": "1.0.0",
            "author": {"name": "AI Hive(R)"},
            "license": "MIT",
            "repository": "https://example.com/repo",
            "homepage": "https://example.com/repo",
        }),
        encoding="utf-8",
    )
    reg = PluginRegistry(plugins_dir)
    report = reg.reload()
    assert report.added == ("rust",)
    assert report.errors == ()


def test_registry_reload_atomic_swap_on_success(tmp_path: Path) -> None:
    """Successful reload swaps the in-memory state in one step."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    _make_plugin(plugins_dir / "rust", id_="rust")
    reg = PluginRegistry(plugins_dir)
    reg.reload()
    first_state = reg.list_ids()
    # Add a new plugin and reload — first-state ids preserved (in
    # ``unchanged``), new id in ``added``.
    _make_plugin(plugins_dir / "python", id_="python")
    report = reg.reload()
    assert set(reg.list_ids()) == set(first_state) | {"python"}
    assert "python" in report.added
