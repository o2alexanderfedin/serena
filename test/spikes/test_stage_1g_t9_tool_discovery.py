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

# Stage 3 (v0.2.0) — 12 Rust + 8 Python ergonomic facades.
_STAGE_3_NAMES: frozenset[str] = frozenset({
    # Rust Wave A
    "scalpel_convert_module_layout",
    "scalpel_change_visibility",
    "scalpel_tidy_structure",
    "scalpel_change_type_shape",
    # Rust Wave B
    "scalpel_change_return_type",
    "scalpel_complete_match_arms",
    "scalpel_extract_lifetime",
    "scalpel_expand_glob_imports",
    # Rust Wave C
    "scalpel_generate_trait_impl_scaffold",
    "scalpel_generate_member",
    "scalpel_expand_macro",
    "scalpel_verify_after_refactor",
    # Python Wave A (pylsp-rope)
    "scalpel_convert_to_method_object",
    "scalpel_local_to_field",
    "scalpel_use_function",
    "scalpel_introduce_parameter",
    # Python Wave B (multi-source)
    "scalpel_generate_from_undefined",
    "scalpel_auto_import_specialized",
    "scalpel_fix_lints",
    "scalpel_ignore_diagnostic",
})

# v1.1 Stream 5 — additional always-on primitives + facades.
_V11_NAMES: frozenset[str] = frozenset({
    "scalpel_reload_plugins",  # Leaf 03 — Q10 explicit-refresh
    "scalpel_confirm_annotations",  # Leaf 06 — ChangeAnnotation review gate
    "scalpel_convert_to_async",  # Leaf 07 — AST-based async conversion
    "scalpel_annotate_return_type",  # Leaf 07 — basedpyright inlay-hint inference
    "scalpel_convert_from_relative_imports",  # Leaf 07 — rope relatives_to_absolutes
})

# v1.1.1 — markdown stream (single-LSP marksman; 4 facades + installer primitive).
_V11_1_NAMES: frozenset[str] = frozenset({
    "scalpel_rename_heading",  # Leaf 02 — marksman textDocument/rename
    "scalpel_split_doc",  # Leaf 02 — split a doc along H1/H2 boundaries
    "scalpel_extract_section",  # Leaf 02 — extract one section into a sibling file
    "scalpel_organize_links",  # Leaf 02 — sort + dedup wiki + markdown links
    "scalpel_install_lsp_servers",  # Leaf 03 — LSP installer infra (marksman PoC)
})

EXPECTED_NAMES: frozenset[str] = (
    _STAGE_1G_NAMES
    | _STAGE_2A_NAMES
    | _STAGE_3_NAMES
    | _V11_NAMES
    | _V11_1_NAMES
)


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
