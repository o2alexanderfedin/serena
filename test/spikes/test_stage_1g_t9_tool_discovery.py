"""T9 — All 8 Stage 1G tools auto-discovered + MCP-tool conversion smoke."""

from __future__ import annotations

import re
from unittest.mock import MagicMock


# Stage 1G — 8 always-on primitive tools.
_STAGE_1G_NAMES: frozenset[str] = frozenset({
    "capabilities_list",
    "capability_describe",
    "apply_capability",
    "dry_run_compose",
    "rollback",
    "transaction_rollback",
    "workspace_health",
    "execute_command",
})

# Stage 2A — 5 ergonomic facades + 13th always-on transaction commit.
_STAGE_2A_NAMES: frozenset[str] = frozenset({
    "split_file",
    "extract",
    "inline",
    "rename",
    "imports_organize",
    "transaction_commit",
})

# Stage 3 (v0.2.0) — 12 Rust + 8 Python ergonomic facades.
_STAGE_3_NAMES: frozenset[str] = frozenset({
    # Rust Wave A
    "convert_module_layout",
    "change_visibility",
    "tidy_structure",
    "change_type_shape",
    # Rust Wave B
    "change_return_type",
    "complete_match_arms",
    "extract_lifetime",
    "expand_glob_imports",
    # Rust Wave C
    "generate_trait_impl_scaffold",
    "generate_member",
    "expand_macro",
    "verify_after_refactor",
    # Python Wave A (pylsp-rope)
    "convert_to_method_object",
    "local_to_field",
    "use_function",
    "introduce_parameter",
    # Python Wave B (multi-source)
    "generate_from_undefined",
    "auto_import_specialized",
    "fix_lints",
    "ignore_diagnostic",
})

# v1.1 Stream 5 — additional always-on primitives + facades.
_V11_NAMES: frozenset[str] = frozenset({
    "reload_plugins",  # Leaf 03 — Q10 explicit-refresh
    "confirm_annotations",  # Leaf 06 — ChangeAnnotation review gate
    "convert_to_async",  # Leaf 07 — AST-based async conversion
    "annotate_return_type",  # Leaf 07 — basedpyright inlay-hint inference
    "convert_from_relative_imports",  # Leaf 07 — rope relatives_to_absolutes
})

# v1.1.1 — markdown stream (single-LSP marksman; 4 facades + installer primitive).
_V11_1_NAMES: frozenset[str] = frozenset({
    "rename_heading",  # Leaf 02 — marksman textDocument/rename
    "split_doc",  # Leaf 02 — split a doc along H1/H2 boundaries
    "extract_section",  # Leaf 02 — extract one section into a sibling file
    "organize_links",  # Leaf 02 — sort + dedup wiki + markdown links
    "install_lsp_servers",  # Leaf 03 — LSP installer infra (marksman PoC)
})

# v1.5 P2 — Java facade stream (single-LSP jdtls).
_V15_P2_NAMES: frozenset[str] = frozenset({
    "generate_constructor",  # P2 — jdtls source.generate.constructor
    "override_methods",  # P2 — jdtls source.generate.overrideMethods
    # NOTE: extract grew a Java arm in P2 but the tool name is unchanged
    # so it stays in _STAGE_2A_NAMES.
})

EXPECTED_NAMES: frozenset[str] = (
    _STAGE_1G_NAMES
    | _STAGE_2A_NAMES
    | _STAGE_3_NAMES
    | _V11_NAMES
    | _V11_1_NAMES
    | _V15_P2_NAMES
)


def test_all_eight_tools_appear_in_iter_subclasses() -> None:
    from serena.tools import (  # noqa: F401 — populates Tool subclass registry
        ApplyCapabilityTool,
        CapabilitiesListTool,
        CapabilityDescribeTool,
        DryRunComposeTool,
        ExecuteCommandTool,
        RollbackTool,
        TransactionRollbackTool,
        WorkspaceHealthTool,
    )

    # Reference each so import isn't unused.
    for sym in (
        ApplyCapabilityTool,
        CapabilitiesListTool,
        CapabilityDescribeTool,
        DryRunComposeTool,
        ExecuteCommandTool,
        RollbackTool,
        TransactionRollbackTool,
        WorkspaceHealthTool,
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
        ApplyCapabilityTool,
        CapabilitiesListTool,
        CapabilityDescribeTool,
        DryRunComposeTool,
        ExecuteCommandTool,
        RollbackTool,
        TransactionRollbackTool,
        WorkspaceHealthTool,
    )

    classes = [
        ApplyCapabilityTool,
        CapabilitiesListTool,
        CapabilityDescribeTool,
        DryRunComposeTool,
        ExecuteCommandTool,
        RollbackTool,
        TransactionRollbackTool,
        WorkspaceHealthTool,
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
    """§5.3 anti-collision: Scalpel facade/primitive names never reuse an
    existing Serena upstream name.

    v2.0 wire-name cleanup (spec 2026-05-03 § 5.1): Scalpel facade classes
    no longer carry a ``Scalpel`` prefix, so we partition by source-module
    instead of class-name prefix. Other Serena tool modules
    (``file_tools``, ``symbol_tools``, ``memory_tools``, ``config_tools``,
    ``workflow_tools``, etc.) MUST NOT register a name that collides with
    a Scalpel facade.
    """
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    _SCALPEL_MODULES = {
        "serena.tools.scalpel_facades",
        "serena.tools.scalpel_primitives",
    }
    serena_names = {
        cls.get_name_from_cls()
        for cls in iter_subclasses(Tool)
        if cls.__module__ not in _SCALPEL_MODULES
    }
    assert EXPECTED_NAMES.isdisjoint(serena_names)


def test_no_emergency_legacy_aliases_pollute_namespace() -> None:
    """Scalpel facade/primitive modules ship exactly the EXPECTED_NAMES
    set, no more, no less.

    v2.0 (spec 2026-05-03 § 5.1): partition by module, not by class-name
    prefix. Legacy ``scalpel_<verb>`` aliases live ONLY in the
    ``ToolRegistry`` deprecation alias map, never as their own class.
    """
    from serena.tools.tools_base import Tool
    from serena.util.inspection import iter_subclasses

    _SCALPEL_MODULES = {
        "serena.tools.scalpel_facades",
        "serena.tools.scalpel_primitives",
    }
    scalpel_names = {
        cls.get_name_from_cls()
        for cls in iter_subclasses(Tool)
        if cls.__module__ in _SCALPEL_MODULES
    }
    assert scalpel_names == EXPECTED_NAMES, (
        f"Scalpel facade/primitive class-name set drifted from "
        f"EXPECTED_NAMES; extras={scalpel_names - EXPECTED_NAMES}, "
        f"missing={EXPECTED_NAMES - scalpel_names}"
    )
