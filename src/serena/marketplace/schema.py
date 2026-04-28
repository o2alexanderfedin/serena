"""Pydantic schema for the published ``marketplace.json`` manifest.

v1.2 reconciliation: this module is the **single source of truth** for the
parent-root ``marketplace.json`` shape consumed by Claude Code marketplaces.
It absorbs the boostvolt-shape contract that the Stage 1J path used to model
under :mod:`serena.refactoring.plugin_schemas`, and replaces the schema-driven
``marketplace.surface.json`` shape that previously coexisted alongside it.

The boostvolt shape is what Claude Code actually reads; the surface-only
fields (``id``, ``language``, ``path``, ``install_hint``, ``schema_version``)
had no runtime consumer and are dropped — language is recoverable from
``.mcp.json``, ``install_hint`` lives in the per-plugin ``verify-scalpel-*``
hook, and ``path`` is just ``./`` + dirname.

All models freeze on construction (``frozen=True``) and reject unknown fields
(``extra="forbid"``) so any drift in the generator output surfaces immediately
as a validation error rather than landing as a silent regression in
``marketplace.json``. The drift-CI gate compares the on-disk file against the
runtime :func:`serena.marketplace.build.build_manifest` output byte-for-byte.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Semver 2.0 with optional pre-release tag. Build metadata is intentionally
# omitted — published plugin versions are bare ``MAJOR.MINOR.PATCH`` (with an
# optional ``-pre`` qualifier) to match the Claude Code marketplace contract.
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$"

# We validate URLs as plain strings (not pydantic ``HttpUrl``) because the
# emitted JSON is consumed by Claude Code marketplaces that expect literal
# strings, and ``HttpUrl`` adds friction at the constructor boundary.
_URL_RE = re.compile(r"^https?://[\w.\-/:?#@!$&'()*+,;=%]+$")


def _validate_url(v: str) -> str:
    if not _URL_RE.match(v):
        raise ValueError(f"Not a valid http(s) URL: {v!r}")
    return v


class _Strict(BaseModel):
    """Strict base — frozen, extra-forbid, populate-by-name."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class AuthorInfo(_Strict):
    """Per-plugin author payload."""

    name: str = Field(min_length=1)
    email: Optional[str] = None
    url: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_url(v) if v is not None else None


class OwnerInfo(_Strict):
    """Top-level marketplace ``owner`` payload."""

    name: str = Field(min_length=1)
    email: Optional[str] = None
    url: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_url(v) if v is not None else None


class ManifestMetadata(_Strict):
    """Top-level ``marketplace.json#metadata`` payload."""

    description: str = Field(min_length=1)
    version: str = Field(pattern=_SEMVER_PATTERN)
    license: str = Field(min_length=1)
    repository: str
    homepage: str

    @field_validator("repository", "homepage")
    @classmethod
    def _check_urls(cls, v: str) -> str:
        return _validate_url(v)


class PluginEntry(_Strict):
    """One row in ``marketplace.json#plugins``."""

    name: str = Field(min_length=1, description="Human-readable plugin name.")
    version: str = Field(
        pattern=_SEMVER_PATTERN,
        description="Semver version of the plugin tree.",
    )
    source: str = Field(
        min_length=1,
        description="Repo-relative path to the plugin tree (with ``./`` prefix).",
    )
    description: str = Field(min_length=1)
    category: str = Field(min_length=1)
    tags: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Free-form keyword tags surfaced in marketplace UIs.",
    )
    author: AuthorInfo


class MarketplaceManifest(_Strict):
    """Top-level ``marketplace.json`` payload (boostvolt-shape)."""

    schema_url: str = Field(
        default="https://anthropic.com/claude-code/marketplace.schema.json",
        alias="$schema",
    )
    generator: str = Field(
        alias="_generator",
        description=(
            "Hand-off banner identifying the generator + revision. Carried "
            "as an alias so JSON serialization preserves the leading "
            "underscore that flags the field as generator-only metadata."
        ),
    )
    name: str = Field(min_length=1)
    metadata: ManifestMetadata
    owner: OwnerInfo
    plugins: tuple[PluginEntry, ...] = Field(
        default_factory=tuple,
        description="Sorted plugin entries; build_manifest sorts by name.",
    )


__all__ = [
    "AuthorInfo",
    "ManifestMetadata",
    "MarketplaceManifest",
    "OwnerInfo",
    "PluginEntry",
]
