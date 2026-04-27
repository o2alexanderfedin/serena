"""Stream 5 / Leaf 03 (v1.1) — in-process plugin registry.

This package houses the runtime plugin/capability registry that backs the
``scalpel_reload_plugins`` MCP tool. The registry scans the parent
o2-scalpel multi-plugin tree (``o2-scalpel-<language>/.claude-plugin/plugin.json``)
and exposes an atomic ``reload()`` operation so a generated plugin can be
picked up without restarting the MCP server (Q10 resolution: explicit
manual refresh, no filesystem watcher).

The published-marketplace schema (``serena.marketplace``) and the
boostvolt-shape ``plugin.json`` schema (``serena.refactoring.plugin_schemas``)
are deliberately separate — this package only validates the boostvolt-shape
manifest the parent plugin tree actually contains.
"""

from __future__ import annotations

from serena.plugins.registry import PluginRegistry
from serena.plugins.reload_report import ReloadReport

__all__ = ["PluginRegistry", "ReloadReport"]
