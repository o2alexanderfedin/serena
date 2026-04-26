"""T6 — discovery.py: sibling-plugin walker + O2_SCALPEL_DISABLE_LANGS."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from serena.refactoring.discovery import (
    PluginRecord,
    discover_sibling_plugins,
    enabled_languages,
)


def _write_plugin(root: Path, owner: str, plugin: str, language: str) -> Path:
    plugin_dir = root / f"{owner}__cc-plugins" / plugin / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = plugin_dir / "plugin.json"
    manifest.write_text(
        json.dumps({"name": plugin, "version": "0.1.0", "scalpel": {"language": language}}),
        encoding="utf-8",
    )
    return plugin_dir.parent


@pytest.fixture(autouse=True)
def _clear_discovery_cache() -> Iterator[None]:
    discover_sibling_plugins.cache_clear()
    yield
    discover_sibling_plugins.cache_clear()


def test_discovers_sibling_plugins(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_plugin(cache, "alex", "scalpel-rust", "rust")
    _write_plugin(cache, "alex", "scalpel-python", "python")
    records = discover_sibling_plugins(cache_root=cache)
    langs = sorted(r.language for r in records)
    assert langs == ["python", "rust"]


def test_discovery_returns_PluginRecord_pydantic_model(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_plugin(cache, "alex", "scalpel-rust", "rust")
    records = discover_sibling_plugins(cache_root=cache)
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, PluginRecord)
    assert rec.language == "rust"
    assert rec.name == "scalpel-rust"
    assert rec.path.is_absolute()


def test_discovery_skips_plugin_without_scalpel_section(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    plugin_dir = cache / "third__random-plugin" / "general" / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": "general", "version": "1"}), encoding="utf-8")
    records = discover_sibling_plugins(cache_root=cache)
    assert records == ()


def test_discovery_skips_malformed_manifest(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    plugin_dir = cache / "alex__cc-plugins" / "scalpel-rust" / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text("{not valid json", encoding="utf-8")
    records = discover_sibling_plugins(cache_root=cache)
    assert records == ()  # malformed → silently skipped (logged at WARNING)


def test_discovery_returns_empty_when_cache_root_missing(tmp_path: Path) -> None:
    records = discover_sibling_plugins(cache_root=tmp_path / "does-not-exist")
    assert records == ()


def test_enabled_languages_strips_disabled_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    _write_plugin(cache, "alex", "scalpel-rust", "rust")
    _write_plugin(cache, "alex", "scalpel-python", "python")
    records = discover_sibling_plugins(cache_root=cache)
    monkeypatch.setenv("O2_SCALPEL_DISABLE_LANGS", "rust")
    enabled = enabled_languages(records)
    assert enabled == frozenset({"python"})


def test_enabled_languages_strips_multiple_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    _write_plugin(cache, "alex", "scalpel-rust", "rust")
    _write_plugin(cache, "alex", "scalpel-python", "python")
    records = discover_sibling_plugins(cache_root=cache)
    monkeypatch.setenv("O2_SCALPEL_DISABLE_LANGS", "rust,python")
    enabled = enabled_languages(records)
    assert enabled == frozenset()


def test_enabled_languages_returns_all_when_env_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    _write_plugin(cache, "alex", "scalpel-rust", "rust")
    monkeypatch.delenv("O2_SCALPEL_DISABLE_LANGS", raising=False)
    records = discover_sibling_plugins(cache_root=cache)
    assert enabled_languages(records) == frozenset({"rust"})


def test_default_cache_root_is_under_home() -> None:
    """Without an explicit cache_root, the function probes ~/.claude/plugins/cache."""
    from serena.refactoring.discovery import default_cache_root
    expected = (Path.home() / ".claude" / "plugins" / "cache").resolve()
    assert default_cache_root() == expected
