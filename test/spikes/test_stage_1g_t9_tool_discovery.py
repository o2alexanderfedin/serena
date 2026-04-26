"""T9 — All 8 Stage 1G tools auto-discovered + MCP-tool conversion smoke."""

from __future__ import annotations

import re
from unittest.mock import MagicMock


# Stage 1G — 8 always-on primitive tools.
_STAGE_1G_NAMES: frozenset[str] = frozenset({
    "scalpel_capabilities_list",
    "scalpel_capability_describe",
    "scalpel_apply_capability",
    "scalpel_dry_run_compose",
    "scalpel_rollback",
    "scalpel_transaction_rollback",
    "scalpel_workspace_health",
    "scalpel_execute_command",
})

# Stage 2A — 5 ergonomic facades + 13th always-on transaction commit.
_STAGE_2A_NAMES: frozenset[str] = frozenset({
    "scalpel_split_file",
    "scalpel_extract",
    "scalpel_inline",
    "scalpel_rename",
    "scalpel_imports_organize",
    "scalpel_transaction_commit",
})

EXPECTED_NAMES: frozenset[str] = _STAGE_1G_NAMES | _STAGE_2A_NAMES


def test_all_eight_tools_appear_in_iter_subclasses() -> None:
    from serena.tools import (  # noqa: F401 — populates Tool subclass registry
        ScalpelApplyCapabilityTool,
        ScalpelCapabilitiesListTool,
        ScalpelCapabilityDescribeTool,
        ScalpelDryRunComposeTool,
        ScalpelExecuteCommandTool,
        ScalpelRollbackTool,
        ScalpelTransactionRollbackTool,
        ScalpelWorkspaceHealthTool,
    )

    # Reference each so import isn't unused.
    for sym in (
        ScalpelApplyCapabilityTool,
        ScalpelCapabilitiesListTool,
        ScalpelCapabilityDescribeTool,
        ScalpelDryRunComposeTool,
        ScalpelExecuteCommandTool,
        ScalpelRollbackTool,
        ScalpelTransactionRollbackTool,
        ScalpelWorkspaceHealthTool,
    ):
        assert sym is not None
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    missing = EXPECTED_NAMES - discovered
    assert not missing, f"Stage 1G tools missing from iter_subclasses: {missing}"


def test_each_apply_docstring_is_under_thirty_words() -> None:
    """§5.4 router-signage rule: <=30 words per apply docstring."""
    from serena.tools import (
        ScalpelApplyCapabilityTool,
        ScalpelCapabilitiesListTool,
        ScalpelCapabilityDescribeTool,
        ScalpelDryRunComposeTool,
        ScalpelExecuteCommandTool,
        ScalpelRollbackTool,
        ScalpelTransactionRollbackTool,
        ScalpelWorkspaceHealthTool,
    )

    classes = [
        ScalpelApplyCapabilityTool,
        ScalpelCapabilitiesListTool,
        ScalpelCapabilityDescribeTool,
        ScalpelDryRunComposeTool,
        ScalpelExecuteCommandTool,
        ScalpelRollbackTool,
        ScalpelTransactionRollbackTool,
        ScalpelWorkspaceHealthTool,
    ]
    for cls in classes:
        doc = cls.apply.__doc__ or ""
        head = doc.split(":param", 1)[0].split(":return", 1)[0]
        word_count = len(re.findall(r"\b\w+\b", head))
        assert word_count <= 30, (
            f"{cls.__name__}.apply docstring head exceeds 30 words "
            f"({word_count}): {head!r}"
        )


def test_make_mcp_tool_succeeds_for_every_class() -> None:
    """SerenaMCPFactory.make_mcp_tool must accept each tool unchanged."""
    from serena.mcp import SerenaMCPFactory
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    agent = MagicMock(name="SerenaAgent")
    agent.get_context.return_value = MagicMock(tool_description_overrides={})
    for cls in iter_subclasses(Tool):
        if cls.get_name_from_cls() not in EXPECTED_NAMES:
            continue
        tool = cls(agent=agent)
        mcp_tool = SerenaMCPFactory.make_mcp_tool(tool, openai_tool_compatible=False)
        assert mcp_tool.name == cls.get_name_from_cls()
        assert mcp_tool.description  # docstring carried through


def test_no_collision_with_serena_builtin_tool_names() -> None:
    """§5.3 anti-collision: scalpel_* never reuses an existing serena name."""
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    serena_names = {
        cls.get_name_from_cls() for cls in iter_subclasses(Tool)
        if not cls.get_name_from_cls().startswith("scalpel_")
    }
    assert EXPECTED_NAMES.isdisjoint(serena_names)


def test_no_emergency_legacy_aliases_pollute_namespace() -> None:
    """Stage 1G ships exactly 8 scalpel_* names; nothing more."""
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    scalpel_names = {
        cls.get_name_from_cls() for cls in iter_subclasses(Tool)
        if cls.get_name_from_cls().startswith("scalpel_")
    }
    assert scalpel_names == EXPECTED_NAMES, (
        f"Unexpected scalpel_* tools at Stage 1G close: "
        f"{scalpel_names - EXPECTED_NAMES}"
    )
