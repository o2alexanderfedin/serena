"""Stream 5 / Leaf 01 — published-marketplace surface.

Public surface for the ``marketplace.json`` file checked into the parent
o2-scalpel repository root. The published manifest describes which language
plugins ship as part of the distribution and is validated by pydantic so that
drift from the runtime generator output fails CI immediately rather than
landing as a silent regression.

This package is intentionally separate from
:mod:`serena.refactoring.plugin_schemas`, which models the per-plugin
boostvolt-shape ``plugin.json`` consumed by Claude Code marketplaces. The two
schemas describe different artefacts at different layers of the stack.
"""

from __future__ import annotations

from serena.marketplace.schema import MarketplaceManifest, PluginEntry

__all__ = ["MarketplaceManifest", "PluginEntry"]
