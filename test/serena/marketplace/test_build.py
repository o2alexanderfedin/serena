"""Builder tests for the unified ``marketplace.json`` (v1.2 reconciliation).

The builder walks ``repo_root/o2-scalpel-*`` directories that carry a
``.claude-plugin/plugin.json`` and produces the boostvolt-shape manifest
consumed by Claude Code. Per-plugin marketplace-UI fields (``description``,
``category``, ``tags``, ``author``) are read straight from ``plugin.json``
so we have a single source of truth instead of a parallel side-table inside
the marketplace builder.
"""

from __future__ import annotations

import json
from pathlib import Path

from serena.marketplace.build import (
    _generator_banner,
    build_manifest,
    render_manifest_json,
    write_manifest,
)
from serena.marketplace.schema import MarketplaceManifest


def _make_plugin_tree(
    repo_root: Path,
    *,
    dir_name: str,
    plugin_name: str,
    language: str,
    description: str | None = None,
    category: str = "development",
    tags: tuple[str, ...] | None = None,
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
                "description": description or f"plugin for {language}",
                "license": "MIT",
                "repository": "https://github.com/o2services/o2-scalpel",
                "homepage": "https://github.com/o2services/o2-scalpel",
                "author": {"name": "AI Hive(R)"},
                "category": category,
                "tags": list(tags) if tags is not None else [language, "lsp"],
            }
        ),
        encoding="utf-8",
    )
    return root


# --- core walker behaviour ---------------------------------------------


def test_build_manifest_walks_plugin_tree(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-rust",
        plugin_name="o2-scalpel-rust",
        language="rust",
        description="rust plugin",
        tags=("rust", "rust-analyzer", "lsp"),
    )
    m = build_manifest(tmp_path, generator_sha="deadbeefcafe")
    assert isinstance(m, MarketplaceManifest)
    assert len(m.plugins) == 1
    entry = m.plugins[0]
    assert entry.name == "o2-scalpel-rust"
    assert entry.source == "./o2-scalpel-rust"
    assert entry.description == "rust plugin"
    assert entry.category == "development"
    assert entry.tags == ("rust", "rust-analyzer", "lsp")
    assert entry.author.name == "AI Hive(R)"


def test_build_manifest_returns_empty_plugins_when_no_trees(tmp_path: Path) -> None:
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
    assert [p.name for p in m.plugins] == ["o2-scalpel-rust"]


def test_build_manifest_sorts_entries_by_name(tmp_path: Path) -> None:
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
    assert [p.name for p in m.plugins] == ["o2-scalpel-python", "o2-scalpel-rust"]


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
    assert [p.name for p in m.plugins] == ["o2-scalpel-rust"]


# --- top-level metadata -----------------------------------------------


def test_build_manifest_populates_top_level_identity(tmp_path: Path) -> None:
    m = build_manifest(tmp_path, generator_sha="abcdef012345")
    assert m.name == "o2-scalpel"
    assert m.owner.name == "AI Hive(R)"
    assert m.metadata.repository == "https://github.com/o2services/o2-scalpel"
    assert m.metadata.license == "MIT"
    assert "abcdef012345" in m.generator


def test_generator_banner_truncates_sha_to_12_chars() -> None:
    banner = _generator_banner("abcdef0123456789abcd")
    assert "abcdef012345" in banner
    assert "abcdef0123456789abcd" not in banner


# --- plugin.json metadata propagation ---------------------------------


def test_build_manifest_propagates_per_plugin_category_and_tags(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-python",
        plugin_name="o2-scalpel-python",
        language="python",
        category="development",
        tags=("python", "pylsp", "lsp", "refactor", "mcp", "scalpel"),
    )
    m = build_manifest(tmp_path)
    entry = m.plugins[0]
    assert entry.category == "development"
    assert entry.tags == ("python", "pylsp", "lsp", "refactor", "mcp", "scalpel")


def test_build_manifest_falls_back_to_default_category_when_missing(tmp_path: Path) -> None:
    """If ``plugin.json`` lacks ``category`` the builder defaults to ``development``."""

    root = tmp_path / "o2-scalpel-rust"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "o2-scalpel-rust",
                "version": "1.0.0",
                "description": "no category",
                "license": "MIT",
                "repository": "https://example.com",
                "homepage": "https://example.com",
                "author": {"name": "AI Hive(R)"},
                "tags": ["rust"],
            }
        ),
        encoding="utf-8",
    )
    m = build_manifest(tmp_path)
    assert m.plugins[0].category == "development"


# --- write + render --------------------------------------------------


def test_write_manifest_lands_at_marketplace_json(tmp_path: Path) -> None:
    _make_plugin_tree(
        tmp_path,
        dir_name="o2-scalpel-rust",
        plugin_name="o2-scalpel-rust",
        language="rust",
    )
    m = build_manifest(tmp_path, generator_sha="cafebabecafe")
    out = write_manifest(tmp_path, m)
    assert out == tmp_path / "marketplace.json"
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["$schema"].endswith("marketplace.schema.json")
    assert payload["_generator"].startswith("Generated by o2-scalpel-newplugin")
    assert payload["plugins"][0]["name"] == "o2-scalpel-rust"


def test_render_manifest_json_is_deterministic(tmp_path: Path) -> None:
    """Two consecutive renders of the same manifest produce identical bytes."""

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
    a = render_manifest_json(build_manifest(tmp_path, generator_sha="x"))
    b = render_manifest_json(build_manifest(tmp_path, generator_sha="x"))
    assert a == b
    assert a.endswith("\n")
