"""PC2 coverage uplift — serena.refactoring.discovery uncovered ranges.

Target line ranges from Phase B coverage analysis:
  L35     default_cache_root() return path
  L58-77  discover_sibling_plugins() body (malformed json, missing scalpel section,
           missing language, valid plugin)
  L86-87  PluginRecord construction exception guard
  L96-98  enabled_languages() with O2_SCALPEL_DISABLE_LANGS env var

Pure unit tests — filesystem manipulated via tmp_path fixture.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from serena.refactoring.discovery import (
    PluginRecord,
    default_cache_root,
    discover_sibling_plugins,
    enabled_languages,
)


# ---------------------------------------------------------------------------
# default_cache_root
# ---------------------------------------------------------------------------


class TestDefaultCacheRoot:
    def test_returns_canonical_path(self) -> None:
        result = default_cache_root()
        assert isinstance(result, Path)
        # Must be under home directory.
        assert str(Path.home()) in str(result)
        assert "plugins" in str(result)
        assert "cache" in str(result)


# ---------------------------------------------------------------------------
# discover_sibling_plugins — filesystem-level tests
# ---------------------------------------------------------------------------


def _write_plugin_manifest(
    cache_root: Path,
    owner: str,
    repo: str,
    plugin_name: str,
    manifest: dict,
) -> Path:
    """Create a plugin directory tree with a manifest."""
    plugin_dir = cache_root / f"{owner}__{repo}" / plugin_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin").mkdir(exist_ok=True)
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return plugin_dir


class TestDiscoverSiblingPlugins:
    def test_nonexistent_root_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent" / "cache"
        result = discover_sibling_plugins(missing)
        assert result == ()

    def test_valid_plugin_discovered(self, tmp_path: Path) -> None:
        # lru_cache must be bypassed by using a unique path each time.
        cache = tmp_path / "cache"
        _write_plugin_manifest(
            cache, "o2alexanderfedin", "o2-scalpel-python", "o2-scalpel-python",
            {
                "name": "o2-scalpel-python",
                "version": "1.0.0",
                "scalpel": {"language": "python"},
            },
        )
        result = discover_sibling_plugins(cache)
        assert len(result) == 1
        assert result[0].language == "python"
        assert result[0].name == "o2-scalpel-python"
        assert result[0].version == "1.0.0"

    def test_plugin_without_scalpel_section_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache2"
        _write_plugin_manifest(
            cache, "org", "plugin", "plugin",
            {"name": "plain-plugin", "version": "0.1.0"},
        )
        result = discover_sibling_plugins(cache)
        assert result == ()

    def test_plugin_with_non_dict_scalpel_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache3"
        _write_plugin_manifest(
            cache, "org", "plugin", "plugin",
            {"name": "bad-scalpel", "scalpel": "not-a-dict"},
        )
        result = discover_sibling_plugins(cache)
        assert result == ()

    def test_plugin_missing_language_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache4"
        _write_plugin_manifest(
            cache, "org", "plugin", "plugin",
            {"name": "no-lang", "scalpel": {}},
        )
        result = discover_sibling_plugins(cache)
        assert result == ()

    def test_plugin_empty_language_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache5"
        _write_plugin_manifest(
            cache, "org", "plugin", "plugin",
            {"name": "empty-lang", "scalpel": {"language": ""}},
        )
        result = discover_sibling_plugins(cache)
        assert result == ()

    def test_malformed_json_manifest_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache6"
        plugin_dir = cache / "org__repo" / "my-plugin"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        cp_dir = plugin_dir / ".claude-plugin"
        cp_dir.mkdir(exist_ok=True)
        manifest_path = cp_dir / "plugin.json"
        manifest_path.write_text("{not valid json", encoding="utf-8")
        result = discover_sibling_plugins(cache)
        assert result == ()

    def test_multiple_plugins_discovered(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache7"
        _write_plugin_manifest(
            cache, "org", "repo1", "rust-plugin",
            {"name": "rust-plugin", "scalpel": {"language": "rust"}},
        )
        _write_plugin_manifest(
            cache, "org", "repo2", "python-plugin",
            {"name": "python-plugin", "scalpel": {"language": "python"}},
        )
        result = discover_sibling_plugins(cache)
        languages = {r.language for r in result}
        assert "rust" in languages
        assert "python" in languages

    def test_plugin_name_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache8"
        _write_plugin_manifest(
            cache, "org", "repo", "my-plugin-dir",
            {"scalpel": {"language": "typescript"}},  # no "name" key
        )
        result = discover_sibling_plugins(cache)
        assert len(result) == 1
        assert result[0].language == "typescript"
        assert result[0].name == "my-plugin-dir"

    def test_version_defaults_to_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache9"
        _write_plugin_manifest(
            cache, "org", "repo", "plugin",
            {"scalpel": {"language": "go"}},  # no "version" key
        )
        result = discover_sibling_plugins(cache)
        assert result[0].version is None


# ---------------------------------------------------------------------------
# enabled_languages
# ---------------------------------------------------------------------------


class TestEnabledLanguages:
    def _records(self, languages: list[str]) -> list[PluginRecord]:
        return [
            PluginRecord(name=f"plugin-{lang}", language=lang, path=Path("/fake"))
            for lang in languages
        ]

    def test_all_enabled_when_no_env_var(self) -> None:
        records = self._records(["python", "rust", "typescript"])
        env = {"O2_SCALPEL_DISABLE_LANGS": ""}
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", "")
            result = enabled_languages(records)
        assert result == frozenset({"python", "rust", "typescript"})

    def test_disable_one_language(self) -> None:
        records = self._records(["python", "rust"])
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", "rust")
            result = enabled_languages(records)
        assert result == frozenset({"python"})

    def test_disable_multiple_languages(self) -> None:
        records = self._records(["python", "rust", "typescript", "go"])
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", "rust,go")
            result = enabled_languages(records)
        assert result == frozenset({"python", "typescript"})

    def test_whitespace_trimmed(self) -> None:
        records = self._records(["python", "rust"])
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", " rust , ")
            result = enabled_languages(records)
        assert "rust" not in result
        assert "python" in result

    def test_empty_entries_ignored(self) -> None:
        records = self._records(["python"])
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", ",,, ,")
            result = enabled_languages(records)
        assert "python" in result

    def test_disable_nonexistent_language_is_noop(self) -> None:
        records = self._records(["python"])
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", "fortran")
            result = enabled_languages(records)
        assert "python" in result

    def test_empty_records_returns_empty_set(self) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", "")
            result = enabled_languages([])
        assert result == frozenset()

    def test_accepts_tuple_records(self) -> None:
        records = (
            PluginRecord(name="plugin-python", language="python", path=Path("/fake")),
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("O2_SCALPEL_DISABLE_LANGS", "")
            result = enabled_languages(records)
        assert "python" in result
