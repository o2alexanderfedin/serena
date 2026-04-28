"""Stage 1J T1 — pydantic v2 schemas for per-plugin artefacts.

Validates the two boundary models that gate every Stage 1J render of a
single plugin tree: ``PluginManifest`` (boostvolt-shape ``plugin.json``)
and ``SkillFrontmatter`` (YAML head of each ``skills/*.md``).

The top-level ``marketplace.json`` aggregator is now modelled by
:mod:`serena.marketplace.schema` (v1.2 reconciliation) and exercised by
``test/serena/marketplace/test_schema.py``; the legacy
``MarketplaceManifest``/``PluginEntry``/``MarketplaceMetadata`` shapes
that used to live here were removed when the parallel surface file
collapsed into the unified ``marketplace.json``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serena.refactoring.plugin_schemas import (
    AuthorInfo,
    PluginManifest,
    SkillFrontmatter,
)


def test_plugin_manifest_minimum_fields() -> None:
    m = PluginManifest(
        name="o2-scalpel-rust",
        description="Scalpel refactor MCP server for Rust via rust-analyzer",
        version="1.0.0",
        author=AuthorInfo(name="AI Hive(R)"),
        license="MIT",
        repository="https://github.com/o2services/o2-scalpel",
        homepage="https://github.com/o2services/o2-scalpel",
    )
    assert m.name == "o2-scalpel-rust"
    assert m.author.name == "AI Hive(R)"


def test_plugin_manifest_rejects_invalid_semver() -> None:
    with pytest.raises(ValidationError):
        PluginManifest(
            name="x",
            description="x",
            version="not-semver",
            author=AuthorInfo(name="x"),
            license="MIT",
            repository="https://example.com",
            homepage="https://example.com",
        )


def test_plugin_manifest_rejects_uppercase_name() -> None:
    with pytest.raises(ValidationError):
        PluginManifest(
            name="O2-Scalpel-Rust",
            description="x",
            version="1.0.0",
            author=AuthorInfo(name="x"),
            license="MIT",
            repository="https://example.com",
            homepage="https://example.com",
        )


def test_skill_frontmatter_default_type_is_skill() -> None:
    sf = SkillFrontmatter(
        name="using-scalpel-split-file",
        description="When user asks to split a file, use scalpel_split_file",
    )
    assert sf.type == "skill"
