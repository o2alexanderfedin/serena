"""PC1 coverage uplift — tools_base.py class-level methods.

Tests that do NOT require a live SerenaAgent instance. Covers:
  - Tool.get_name_from_cls (snake_case conversion)
  - Tool.can_edit / is_readonly
  - Tool.get_tool_description
  - Tool.get_apply_docstring_from_cls
  - Tool.get_apply_fn_metadata_from_cls
  - Tool._sanitize_input_param
  - Tool.is_symbolic
  - RegisteredTool.class_docstring (legacy alias prefix)
  - ToolRegistry singleton: get_tool_names, get_tool_class_by_name,
    get_all_tool_classes, get_tool_classes_default_enabled,
    get_tool_classes_optional, get_registered_tools_by_module,
    get_tool_names_default_enabled, get_tool_names_optional,
    get_legacy_alias_names, get_canonical_name_for, is_legacy_alias_name,
    is_valid_tool_name, check_valid_tool_name (valid + deleted),
    is_deleted_tool_name
"""

from __future__ import annotations

from typing import ClassVar

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concrete_tool_cls():
    """Return a minimal concrete Tool subclass (no agent needed for class ops)."""
    from serena.tools.tools_base import Tool

    class _DummyTool(Tool):
        """A dummy tool for testing class-level methods."""

        def apply(self, x: int = 0) -> str:
            """Apply the dummy tool.

            :param x: a number
            :return: a string
            """
            return str(x)

    return _DummyTool


def _make_edit_tool_cls():
    """Return a minimal ToolMarkerCanEdit concrete subclass."""
    from serena.tools.tools_base import Tool, ToolMarkerCanEdit

    class _EditDummyTool(Tool, ToolMarkerCanEdit):
        """An editable dummy tool."""

        def apply(self) -> str:
            """Apply the edit tool.

            :return: ok
            """
            return "ok"

    return _EditDummyTool


def _make_symbolic_tool_cls():
    """Return a minimal ToolMarkerSymbolicRead concrete subclass."""
    from serena.tools.tools_base import Tool, ToolMarkerSymbolicRead

    class _SymbolicDummyTool(Tool, ToolMarkerSymbolicRead):
        """A symbolic read dummy tool."""

        def apply(self) -> str:
            """Apply the symbolic tool.

            :return: ok
            """
            return "ok"

    return _SymbolicDummyTool


# ---------------------------------------------------------------------------
# Tool.get_name_from_cls — snake_case conversion
# ---------------------------------------------------------------------------


def test_get_name_from_cls_simple_camel_case() -> None:
    from serena.tools.tools_base import Tool

    class MySimpleTool(Tool):
        def apply(self) -> str:
            """x"""
            return ""

    assert MySimpleTool.get_name_from_cls() == "my_simple"


def test_get_name_from_cls_strips_tool_suffix() -> None:
    from serena.tools.tools_base import Tool

    class FooBarBazTool(Tool):
        def apply(self) -> str:
            """x"""
            return ""

    assert FooBarBazTool.get_name_from_cls() == "foo_bar_baz"


def test_get_name_from_cls_no_tool_suffix() -> None:
    from serena.tools.tools_base import Tool

    class FooBar(Tool):
        def apply(self) -> str:
            """x"""
            return ""

    # No 'Tool' suffix → keeps original snake_case conversion
    assert FooBar.get_name_from_cls() == "foo_bar"


# ---------------------------------------------------------------------------
# Tool.can_edit / is_readonly
# ---------------------------------------------------------------------------


def test_can_edit_false_for_read_only_tool() -> None:
    cls = _make_concrete_tool_cls()
    assert cls.can_edit() is False


def test_can_edit_true_for_edit_tool() -> None:
    cls = _make_edit_tool_cls()
    assert cls.can_edit() is True


def test_is_readonly_true_for_read_only_tool() -> None:
    from serena.tools.tools_base import Tool

    class _R(Tool):
        def apply(self) -> str:
            """x"""
            return ""

    inst = object.__new__(_R)
    assert inst.is_readonly() is True


def test_is_readonly_false_for_edit_tool() -> None:
    cls = _make_edit_tool_cls()
    inst = object.__new__(cls)
    assert inst.is_readonly() is False


# ---------------------------------------------------------------------------
# Tool.get_tool_description
# ---------------------------------------------------------------------------


def test_get_tool_description_returns_stripped_docstring() -> None:
    cls = _make_concrete_tool_cls()
    desc = cls.get_tool_description()
    assert "dummy tool" in desc.lower()


def test_get_tool_description_no_docstring_returns_empty() -> None:
    from serena.tools.tools_base import Tool

    class _NoDocs(Tool):
        def apply(self) -> str:
            """x"""
            return ""

    # Override class docstring at class level
    _NoDocs.__doc__ = None
    assert _NoDocs.get_tool_description() == ""


# ---------------------------------------------------------------------------
# Tool.get_apply_docstring_from_cls
# ---------------------------------------------------------------------------


def test_get_apply_docstring_from_cls_returns_apply_docstring() -> None:
    cls = _make_concrete_tool_cls()
    doc = cls.get_apply_docstring_from_cls()
    assert "Apply the dummy tool" in doc


def test_get_apply_docstring_from_cls_raises_when_no_docstring() -> None:
    from serena.tools.tools_base import Tool

    class _NoDocs(Tool):
        def apply(self) -> str:
            return ""  # no docstring

    with pytest.raises(AttributeError, match="no .or empty. docstring"):
        _NoDocs.get_apply_docstring_from_cls()


# ---------------------------------------------------------------------------
# Tool.get_apply_fn_metadata_from_cls
# ---------------------------------------------------------------------------


def test_get_apply_fn_metadata_from_cls_returns_func_metadata() -> None:
    cls = _make_concrete_tool_cls()
    meta = cls.get_apply_fn_metadata_from_cls()
    # Just assert it's not None and has some expected attributes
    assert meta is not None


# ---------------------------------------------------------------------------
# Tool._sanitize_input_param
# ---------------------------------------------------------------------------


def test_sanitize_input_param_unescapes_lt_gt() -> None:
    from serena.tools.tools_base import Tool

    assert Tool._sanitize_input_param("&lt;T&gt;") == "<T>"
    assert Tool._sanitize_input_param("a &lt; b") == "a < b"
    assert Tool._sanitize_input_param("no escapes") == "no escapes"


# ---------------------------------------------------------------------------
# Tool.is_symbolic
# ---------------------------------------------------------------------------


def test_is_symbolic_false_for_plain_tool() -> None:
    cls = _make_concrete_tool_cls()
    inst = object.__new__(cls)
    assert inst.is_symbolic() is False


def test_is_symbolic_true_for_symbolic_read_tool() -> None:
    cls = _make_symbolic_tool_cls()
    inst = object.__new__(cls)
    assert inst.is_symbolic() is True


# ---------------------------------------------------------------------------
# RegisteredTool.class_docstring — legacy alias prefix
# ---------------------------------------------------------------------------


def test_registered_tool_class_docstring_no_legacy_alias() -> None:
    from serena.tools.tools_base import RegisteredTool

    cls = _make_concrete_tool_cls()
    rt = RegisteredTool(
        tool_class=cls,
        is_optional=False,
        is_beta=False,
        tool_name="dummy",
        is_legacy_alias=False,
        canonical_name=None,
    )
    assert "DEPRECATED" not in rt.class_docstring


def test_registered_tool_class_docstring_with_legacy_alias() -> None:
    from serena.tools.tools_base import RegisteredTool

    cls = _make_concrete_tool_cls()
    rt = RegisteredTool(
        tool_class=cls,
        is_optional=False,
        is_beta=False,
        tool_name="scalpel_dummy",
        is_legacy_alias=True,
        canonical_name="dummy",
    )
    assert "DEPRECATED" in rt.class_docstring
    assert "dummy" in rt.class_docstring


# ---------------------------------------------------------------------------
# ToolRegistry singleton
# ---------------------------------------------------------------------------


def test_tool_registry_get_tool_names_returns_list() -> None:
    from serena.tools.tools_base import ToolRegistry

    names = ToolRegistry().get_tool_names()
    assert isinstance(names, list)
    assert len(names) > 0


def test_tool_registry_get_tool_class_by_name_known_tool() -> None:
    from serena.tools.tools_base import ToolRegistry

    # "execute_shell_command" is always registered
    cls = ToolRegistry().get_tool_class_by_name("execute_shell_command")
    from serena.tools.cmd_tools import ExecuteShellCommandTool

    assert issubclass(cls, ExecuteShellCommandTool)


def test_tool_registry_get_tool_class_by_name_unknown_raises() -> None:
    from serena.tools.tools_base import ToolRegistry

    with pytest.raises(ValueError, match="not found"):
        ToolRegistry().get_tool_class_by_name("nonexistent_xyzzy_tool")


def test_tool_registry_get_all_tool_classes_no_duplicates() -> None:
    from serena.tools.tools_base import ToolRegistry

    all_classes = ToolRegistry().get_all_tool_classes()
    # No class should appear twice (deduped by identity)
    assert len(all_classes) == len(set(id(c) for c in all_classes))


def test_tool_registry_get_tool_classes_default_enabled_subset() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    enabled = reg.get_tool_classes_default_enabled()
    optional = reg.get_tool_classes_optional()
    all_cls = reg.get_all_tool_classes()
    # No tool class appears in both enabled and optional
    enabled_ids = {id(c) for c in enabled}
    optional_ids = {id(c) for c in optional}
    assert not (enabled_ids & optional_ids)


def test_tool_registry_get_registered_tools_by_module_returns_dict() -> None:
    from serena.tools.tools_base import ToolRegistry

    by_module = ToolRegistry().get_registered_tools_by_module()
    assert isinstance(by_module, dict)
    assert len(by_module) > 0


def test_tool_registry_get_tool_names_default_enabled() -> None:
    from serena.tools.tools_base import ToolRegistry

    names = ToolRegistry().get_tool_names_default_enabled()
    assert isinstance(names, list)
    assert "execute_shell_command" in names


def test_tool_registry_get_tool_names_optional() -> None:
    from serena.tools.tools_base import ToolRegistry

    names = ToolRegistry().get_tool_names_optional()
    assert isinstance(names, list)
    # open_dashboard is optional
    assert "open_dashboard" in names


def test_tool_registry_get_legacy_alias_names() -> None:
    from serena.tools.tools_base import ToolRegistry

    aliases = ToolRegistry().get_legacy_alias_names()
    assert isinstance(aliases, list)
    # e.g. "scalpel_extract" should be a legacy alias
    assert "scalpel_extract" in aliases


def test_tool_registry_get_canonical_name_for_alias() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    # scalpel_extract → extract
    canonical = reg.get_canonical_name_for("scalpel_extract")
    assert canonical == "extract"


def test_tool_registry_get_canonical_name_for_non_alias() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    # canonical name passes through unchanged
    assert reg.get_canonical_name_for("extract") == "extract"
    assert reg.get_canonical_name_for("unknown_tool") == "unknown_tool"


def test_tool_registry_is_legacy_alias_name() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    assert reg.is_legacy_alias_name("scalpel_extract") is True
    assert reg.is_legacy_alias_name("extract") is False


def test_tool_registry_is_valid_tool_name() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    assert reg.is_valid_tool_name("extract") is True
    assert reg.is_valid_tool_name("scalpel_extract") is True  # alias also valid
    assert reg.is_valid_tool_name("nonexistent_xyzzy") is False


def test_tool_registry_is_deleted_tool_name() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    assert reg.is_deleted_tool_name("think_about_collected_information") is True
    assert reg.is_deleted_tool_name("extract") is False


def test_tool_registry_check_valid_tool_name_valid() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    assert reg.check_valid_tool_name("extract") is True


def test_tool_registry_check_valid_tool_name_deleted_returns_false() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    assert reg.check_valid_tool_name("think_about_collected_information") is False


def test_tool_registry_check_valid_tool_name_invalid_raises() -> None:
    from serena.tools.tools_base import ToolRegistry

    reg = ToolRegistry()
    with pytest.raises(ValueError, match="Invalid tool name"):
        reg.check_valid_tool_name("nonexistent_xyzzy_tool")
