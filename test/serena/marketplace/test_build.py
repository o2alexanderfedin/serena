"""Stream 5 / Leaf 01 Task 2 — ``build_manifest`` walks plugin trees.

The manifest builder discovers plugins by walking ``repo_root/o2-scalpel-*``
directories that carry a ``.claude-plugin/plugin.json``. The published-
marketplace layout in this repository sits one level under the parent root
(``o2-scalpel-rust/``, ``o2-scalpel-python/``) rather than under a nested
``plugins/`` directory, so the walker is parent-root-relative. See the leaf
brief's path-correction note (a) for rationale.
"""

from __future__ import annotations

import json
from pathlib import Path

from serena.marketplace.build import build_manifest
from serena.marketplace.schema import MarketplaceManifest


def _make_plugin_tree(
    repo_root: Path,
    *,
    dir_name: str,
    plugin_name: str,
    language: str,
    version: str = "1.0.0",
) -> Path:
    """Helper: write a minimal ``o2-scalpel-<lang>/`` tree under ``repo_root``."""

    root = repo_root / dir_name
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "version": version,
                "description": f"plugin for {language}",
                "license": "MIT",
                "repository": "https://example.com",
                "homepage": "https://example.com",
                "author": {"name": "AI Hive(R)"},
            }
        ),
        encoding="utf-8",
    )
    # ``.mcp.json`` carries the language id used to derive the language field.
    (root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    f"scalpel-{language}": {
                        "command": "uvx",
                        "args": ["serena-mcp", "--language", language],
                        "env": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return root


def test_build_manifest_walks_plugin_tree(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-rust",
        plugin_name="o2-scalpel-rust",
        language="rust",
    )
    m = build_manifest(tmp_path)
    assert isinstance(m, MarketplaceManifest)
    assert len(m.plugins) == 1
    entry = m.plugins[0]
    assert entry.id == "o2-scalpel-rust"
    assert entry.name == "o2-scalpel-rust"
    assert entry.language == "rust"
    assert entry.path == "o2-scalpel-rust"
    assert entry.version == "1.0.0"
    assert entry.install_hint == "rustup component add rust-analyzer"


def test_build_manifest_returns_empty_when_no_plugins(tmp_path: Path) -> None:
    m = build_manifest(tmp_path)
    assert m.plugins == ()


def test_build_manifest_skips_dirs_without_plugin_json(tmp_path: Path) -> None:
    (tmp_path / "o2-scalpel-bogus").mkdir()  # missing .claude-plugin/plugin.json
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-rust",
        plugin_name="o2-scalpel-rust",
        language="rust",
    )
    m = build_manifest(tmp_path)
    assert [p.id for p in m.plugins] == ["o2-scalpel-rust"]


def test_build_manifest_sorts_entries_by_id(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-rust",
        plugin_name="o2-scalpel-rust",
        language="rust",
    )
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-python",
        plugin_name="o2-scalpel-python",
        language="python",
    )
    m = build_manifest(tmp_path)
    assert [p.id for p in m.plugins] == ["o2-scalpel-python", "o2-scalpel-rust"]


def test_build_manifest_install_hint_for_known_language(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-python",
        plugin_name="o2-scalpel-python",
        language="python",
    )
    m = build_manifest(tmp_path)
    assert m.plugins[0].install_hint == "pipx install python-lsp-server"


def test_build_manifest_install_hint_empty_for_unknown_language(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-klingon",
        plugin_name="o2-scalpel-klingon",
        language="klingon",
    )
    m = build_manifest(tmp_path)
    assert m.plugins[0].install_hint == ""


def test_build_manifest_falls_back_to_dirname_when_mcp_json_missing(tmp_path: Path) -> None:
    """If ``.mcp.json`` is absent, the language is derived from the directory name."""

    root = tmp_path / "o2-scalpel-rust"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "o2-scalpel-rust",
                "version": "1.0.0",
                "description": "no mcp",
                "license": "MIT",
                "repository": "https://example.com",
                "homepage": "https://example.com",
                "author": {"name": "AI Hive(R)"},
            }
        ),
        encoding="utf-8",
    )
    m = build_manifest(tmp_path)
    assert m.plugins[0].language == "rust"


def test_build_manifest_ignores_non_plugin_dirs(tmp_path: Path) -> None:
    """Walker only considers ``o2-scalpel-*`` siblings, not arbitrary dirs."""

    (tmp_path / "docs").mkdir()  # decoy that should never match
    (tmp_path / "docs" / ".claude-plugin").mkdir()
    (tmp_path / "docs" / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "decoy", "version": "1.0.0"}), encoding="utf-8"
    )
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-rust",
        plugin_name="o2-scalpel-rust",
        language="rust",
    )
    m = build_manifest(tmp_path)
    assert [p.id for p in m.plugins] == ["o2-scalpel-rust"]
