"""Stream 5 / Leaf 03 Task 4 — registration smoke test.

The spec's Task 4 calls for an MCP-boundary smoke test, but
``vendor/serena`` does not yet ship an in-process MCP harness fixture.
Per the leaf 03 adapt-as-you-go guidance, we exercise the same contract
(auto-discovery + snake-cased name) via :func:`iter_subclasses(Tool)` —
the very mechanism :class:`SerenaMCPFactory` uses internally to
populate its tool list (``serena/mcp.py`` line 249).
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from serena.tools.scalpel_primitives import ReloadPluginsTool
from serena.tools.tools_base import Tool
from serena.util.inspection import iter_subclasses


def test_reload_tool_appears_in_iter_subclasses() -> None:
    """Stage 1G's auto-registration mechanism picks up the new tool."""
    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    assert "reload_plugins" in discovered


def test_reload_tool_class_name_matches_snake_cased_form() -> None:
    """``Tool.get_name_from_cls`` strips the ``Tool`` suffix and snake-cases."""
    assert ReloadPluginsTool.get_name_from_cls() == "reload_plugins"


def test_reload_tool_apply_docstring_under_thirty_words() -> None:
    """§5.4 router-signage rule mirrors the Stage 1G primitive contract."""
    doc = ReloadPluginsTool.apply.__doc__ or ""
    head = doc.split(":param", 1)[0].split(":return", 1)[0]
    word_count = len(re.findall(r"\b\w+\b", head))
    assert word_count <= 30, (
        f"ReloadPluginsTool.apply docstring head exceeds 30 words "
        f"({word_count}): {head!r}"
    )


def test_reload_tool_class_docstring_present() -> None:
    """Class docstring carries through to ``mcp_tool.description``."""
    assert ReloadPluginsTool.__doc__
    assert ReloadPluginsTool.__doc__.strip()


def test_reload_tool_make_mcp_tool_succeeds() -> None:
    """``SerenaMCPFactory.make_mcp_tool`` accepts the tool unchanged.

    Mirrors ``test_make_mcp_tool_succeeds_for_every_class`` in
    ``test_stage_1g_t9_tool_discovery.py`` — proves the new tool is
    fully wire-compatible with the MCP factory the production server
    uses to publish each ``Tool`` subclass over the JSON-RPC boundary.
    """
    from serena.mcp import SerenaMCPFactory

    agent = MagicMock(name="SerenaAgent")
    agent.get_context.return_value = MagicMock(tool_description_overrides={})
    tool = ReloadPluginsTool(agent=agent)
    mcp_tool = SerenaMCPFactory.make_mcp_tool(tool, openai_tool_compatible=False)
    assert mcp_tool.name == "reload_plugins"
    assert mcp_tool.description  # docstring carried through


def test_reload_tool_exported_from_tools_package() -> None:
    """``from serena.tools import ReloadPluginsTool`` works.

    The ``serena.tools`` namespace re-exports via ``*`` from
    ``scalpel_primitives``; the new tool must be in ``__all__`` for the
    star-import to surface it at the top level.
    """
    from serena import tools as tools_pkg

    assert hasattr(tools_pkg, "ReloadPluginsTool")
    assert tools_pkg.ReloadPluginsTool is ReloadPluginsTool
