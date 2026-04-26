"""Pydantic v2 schemas for Stage 1J generated artefacts.

Three boundary models gate every Stage 1J render:

* :class:`PluginManifest` — boostvolt-shape ``plugin.json`` consumed
  by Claude Code marketplaces.
* :class:`SkillFrontmatter` — YAML head of each ``skills/*.md``.
* :class:`MarketplaceManifest` — top-level ``marketplace.json`` aggregating
  all language plugins for the o2-scalpel marketplace.

All models are frozen with ``extra="forbid"`` so any drift in the
generator surfaces immediately as a validation error rather than a
silent extra field in the emitted JSON.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Semver 2.0 with optional pre-release and build metadata. We do not allow
# leading "v"; Claude Code marketplaces expect bare "MAJOR.MINOR.PATCH".
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?(?:\+[\w.]+)?$")

# We validate URLs as plain strings (not pydantic ``HttpUrl``) because the
# emitted JSON is consumed by Claude Code marketplaces that expect literal
# strings, and ``HttpUrl`` adds friction at the constructor boundary.
_URL_RE = re.compile(r"^https?://[\w.\-/:?#@!$&'()*+,;=%]+$")


def _validate_url(v: str) -> str:
    if not _URL_RE.match(v):
        raise ValueError(f"Not a valid http(s) URL: {v!r}")
    return v


class _Strict(BaseModel):
    """Strict base — frozen, extra-forbid, whitespace-trim."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class AuthorInfo(_Strict):
    """``plugin.json#author`` payload."""

    name: str = Field(min_length=1)
    email: str | None = None
    url: str | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_url(v) if v is not None else None


class OwnerInfo(_Strict):
    """``marketplace.json#owner`` payload."""

    name: str = Field(min_length=1)
    email: str | None = None
    url: str | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_url(v) if v is not None else None


class PluginManifest(_Strict):
    """boostvolt-shape ``plugin.json`` — emitted into ``.claude-plugin/``."""

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9\-]*$")
    description: str = Field(min_length=1)
    version: str
    author: AuthorInfo
    license: str = Field(min_length=1)
    repository: str
    homepage: str

    @field_validator("version")
    @classmethod
    def _check_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"Not a valid semver string: {v!r}")
        return v

    @field_validator("repository", "homepage")
    @classmethod
    def _check_urls(cls, v: str) -> str:
        return _validate_url(v)


class SkillFrontmatter(_Strict):
    """YAML head of each ``skills/*.md`` file."""

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9\-]*$")
    description: str = Field(min_length=1)
    type: Literal["skill"] = "skill"


class PluginEntry(_Strict):
    """One row in ``marketplace.json#plugins``."""

    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    description: str | None = None


class MarketplaceMetadata(_Strict):
    """Optional ``marketplace.json#metadata`` payload."""

    version: str = "1.0.0"
    license: str = "MIT"


class MarketplaceManifest(_Strict):
    """Top-level ``marketplace.json`` aggregating all language plugins."""

    schema_url: str = Field(
        default="https://anthropic.com/claude-code/marketplace.schema.json",
        alias="$schema",
    )
    name: str = Field(min_length=1)
    metadata: MarketplaceMetadata = Field(default_factory=MarketplaceMetadata)
    owner: OwnerInfo
    plugins: list[PluginEntry] = Field(min_length=1)


__all__ = [
    "AuthorInfo",
    "MarketplaceManifest",
    "MarketplaceMetadata",
    "OwnerInfo",
    "PluginEntry",
    "PluginManifest",
    "SkillFrontmatter",
]
