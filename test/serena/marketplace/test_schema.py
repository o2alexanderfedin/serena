"""Stream 5 / Leaf 01 Task 1 — pydantic schema for the published marketplace.

The published-marketplace schema (under ``serena.marketplace``) is distinct from
the per-plugin internal ``serena.refactoring.plugin_schemas`` shape: this one
describes the **distribution surface** at the parent ``o2-scalpel`` repo root
(``id`` / ``name`` / ``language`` / ``path`` / ``version`` / ``install_hint``),
not the boostvolt-shape consumed by Claude Code marketplaces.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serena.marketplace.schema import MarketplaceManifest, PluginEntry


def test_plugin_entry_requires_id_name_language_path() -> None:
    e = PluginEntry(
        id="rust-analyzer",
        name="o2-scalpel Rust",
        language="rust",
        path="o2-scalpel-rust",
        version="0.1.0",
        install_hint="rustup component add rust-analyzer",
    )
    assert e.id == "rust-analyzer"
    assert e.name == "o2-scalpel Rust"
    assert e.language == "rust"
    assert e.install_hint == "rustup component add rust-analyzer"


def test_plugin_entry_rejects_unknown_field() -> None:
    # ``unknown_field`` is passed via ``**kwargs`` so static type checkers
    # don't flag the deliberately-bad keyword (pydantic's ``extra="forbid"``
    # is what's under test here, not the type checker).
    bad_kwargs = {
        "id": "x",
        "name": "x",
        "language": "x",
        "path": "x",
        "version": "0.1.0",
        "unknown_field": "boom",
    }
    with pytest.raises(ValidationError):
        PluginEntry(**bad_kwargs)


def test_plugin_entry_rejects_bad_semver() -> None:
    with pytest.raises(ValidationError):
        PluginEntry(
            id="x",
            name="x",
            language="x",
            path="x",
            version="not-a-version",
        )


def test_plugin_entry_default_install_hint_is_empty_string() -> None:
    e = PluginEntry(
        id="x",
        name="x",
        language="x",
        path="x",
        version="0.1.0",
    )
    assert e.install_hint == ""


def test_plugin_entry_is_frozen() -> None:
    e = PluginEntry(
        id="x",
        name="x",
        language="x",
        path="x",
        version="0.1.0",
    )
    with pytest.raises(ValidationError):
        e.id = "y"  # type: ignore[misc]


def test_marketplace_manifest_round_trip() -> None:
    m = MarketplaceManifest(
        plugins=(
            PluginEntry(
                id="o2-scalpel-rust",
                name="o2-scalpel-rust",
                language="rust",
                path="o2-scalpel-rust",
                version="1.0.0",
                install_hint="rustup component add rust-analyzer",
            ),
        )
    )
    assert m.schema_version == 1
    payload = m.model_dump()
    assert payload["schema_version"] == 1
    assert payload["plugins"][0]["id"] == "o2-scalpel-rust"


def test_marketplace_manifest_rejects_unknown_field() -> None:
    bad_kwargs = {"plugins": (), "unknown": "boom"}
    with pytest.raises(ValidationError):
        MarketplaceManifest(**bad_kwargs)
