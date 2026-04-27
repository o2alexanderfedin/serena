"""Pydantic schema for the published ``marketplace.json`` surface.

This is the **distribution-surface** schema for the o2-scalpel multi-plugin
repository (``o2alexanderfedin/claude-code-plugins`` per Q11 resolution): it
records which language plugins ship as part of the marketplace, the
repo-relative path to each plugin tree, and the per-language LSP install hint
surfaced to operators when a SessionStart probe fails.

The schema is deliberately **not** the same as
:class:`serena.refactoring.plugin_schemas.MarketplaceManifest` — that one
models the boostvolt-shape ``marketplace.json`` consumed *by* Claude Code
marketplaces, while this one models the manifest *we* publish *as* the
marketplace. Keeping them separate avoids overloading a single pydantic model
with two divergent contracts.

All models freeze on construction (``frozen=True``) and reject unknown fields
(``extra="forbid"``) so any drift in the generator output surfaces immediately
as a validation error rather than landing as a silent regression in
``marketplace.json``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Semver 2.0 with optional pre-release tag. Build metadata is intentionally
# omitted — published plugin versions are bare ``MAJOR.MINOR.PATCH`` (with an
# optional ``-pre`` qualifier) to match the Claude Code marketplace contract.
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$"


class PluginEntry(BaseModel):
    """One row in ``marketplace.json#plugins``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="Stable plugin identifier.")
    name: str = Field(min_length=1, description="Human-readable plugin name.")
    language: str = Field(
        min_length=1,
        description="Target language id (e.g. ``rust``, ``python``).",
    )
    path: str = Field(
        min_length=1,
        description="Repo-relative path to the plugin tree.",
    )
    version: str = Field(
        pattern=_SEMVER_PATTERN,
        description="Semver version of the plugin tree.",
    )
    install_hint: str = Field(
        default="",
        description=(
            "Per-language LSP install hint surfaced when a SessionStart "
            "probe fails. Empty string means no hint is published."
        ),
    )


class MarketplaceManifest(BaseModel):
    """Top-level ``marketplace.json`` payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    plugins: tuple[PluginEntry, ...] = Field(
        default_factory=tuple,
        description="Sorted plugin entries; build_manifest sorts by id.",
    )


__all__ = ["MarketplaceManifest", "PluginEntry"]
