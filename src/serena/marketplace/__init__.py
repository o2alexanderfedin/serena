"""Stream 5 / Leaf 01 + v1.2 reconciliation — unified marketplace surface.

Public surface for the ``marketplace.json`` file checked into the parent
o2-scalpel repository root. The published manifest describes which language
plugins ship as part of the distribution and is validated by pydantic so that
drift from the runtime generator output fails CI immediately rather than
landing as a silent regression.

v1.2 reconciliation collapsed the previous parallel ``marketplace.surface.json``
(schema-driven, engine-internal) into this boostvolt-shape ``marketplace.json``.
The unified manifest is the single source of truth consumed by Claude Code
marketplaces; per-plugin marketplace-UI metadata (``description``, ``category``,
``tags``, ``author``) is read from each plugin tree's
``.claude-plugin/plugin.json`` (modelled by
:class:`serena.refactoring.plugin_schemas.PluginManifest`), so the marketplace
builder remains a thin aggregator with no parallel side-table.
"""

from __future__ import annotations

from serena.marketplace.schema import MarketplaceManifest, PluginEntry

__all__ = ["MarketplaceManifest", "PluginEntry"]
