"""Pydantic v2 schemas for Stage 1J generated per-plugin artefacts.

Two boundary models gate every Stage 1J render of a single plugin tree:

* :class:`PluginManifest` — boostvolt-shape ``plugin.json`` consumed
  by Claude Code marketplaces; emitted into ``.claude-plugin/``.
* :class:`SkillFrontmatter` — YAML head of each ``skills/*.md``.

The supporting :class:`AuthorInfo` and :class:`OwnerInfo` payloads are
shared by the per-plugin manifest and the parent-root marketplace
manifest (which lives at :mod:`serena.marketplace.schema`).

v1.2 reconciliation moved the top-level ``marketplace.json`` shape
(previously also modelled here as ``MarketplaceManifest`` /
``PluginEntry`` / ``MarketplaceMetadata``) out to
:mod:`serena.marketplace.schema`, the single source of truth. The
legacy classes were removed because keeping a parallel shape here
violates DRY — the marketplace builder reads per-plugin ``plugin.json``
files (this module) and renders the unified ``marketplace.json``
(the marketplace package).

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
    """boostvolt-shape ``plugin.json`` — emitted into ``.claude-plugin/``.

    v1.2 adds ``category`` and ``tags`` so the published ``marketplace.json``
    can derive its per-plugin marketplace-UI metadata from a single source of
    truth (the per-plugin ``plugin.json``) instead of carrying a parallel
    table inside the marketplace builder.
    """

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9\-]*$")
    description: str = Field(min_length=1)
    version: str
    author: AuthorInfo
    license: str = Field(min_length=1)
    repository: str
    homepage: str
    category: str = Field(
        default="development",
        min_length=1,
        description=(
            "Marketplace-UI category. Defaults to ``development`` for every "
            "scalpel plugin we ship; keep here so future categories (e.g. "
            "``testing``, ``ci``) can be opted into per-plugin without "
            "touching the marketplace builder."
        ),
    )
    tags: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Free-form marketplace-UI keyword tags. Order-preserving so the "
            "generator can stable-sort by significance (language first, "
            "then lsp cmd, then generic ``lsp``/``refactor``/``mcp``/"
            "``scalpel``)."
        ),
    )

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


__all__ = [
    "AuthorInfo",
    "OwnerInfo",
    "PluginManifest",
    "SkillFrontmatter",
]
