"""Stage 1J T1 — pydantic v2 schemas for emitted artefacts.

Validates the three boundary models that gate every Stage 1J render:
``PluginManifest`` (boostvolt-shape ``plugin.json``), ``SkillFrontmatter``
(YAML head of each ``skills/*.md``), and ``MarketplaceManifest``
(top-level aggregator).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serena.refactoring.plugin_schemas import (
    AuthorInfo,
    MarketplaceManifest,
    OwnerInfo,
    PluginEntry,
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


def test_marketplace_manifest_with_two_plugins() -> None:
    mm = MarketplaceManifest(
        name="o2-scalpel",
        owner=OwnerInfo(name="AI Hive(R)"),
        plugins=[
            PluginEntry(name="o2-scalpel-rust", source="./o2-scalpel-rust"),
            PluginEntry(name="o2-scalpel-python", source="./o2-scalpel-python"),
        ],
    )
    assert len(mm.plugins) == 2
    assert mm.schema_url.endswith("marketplace.schema.json")
