"""Stage 2A T10 — registry smoke + tool-name + docstring contract."""
from __future__ import annotations

import pytest

import serena.tools as tools_module
from serena.tools.facade_support import get_apply_source
from serena.tools.tools_base import Tool


SCALPEL_2A_TOOLS = [
    "ScalpelSplitFileTool",
    "ScalpelExtractTool",
    "ScalpelInlineTool",
    "ScalpelRenameTool",
    "ScalpelImportsOrganizeTool",
    "ScalpelTransactionCommitTool",
]


@pytest.mark.parametrize("name", SCALPEL_2A_TOOLS)
def test_2a_tool_is_reexported_from_serena_tools(name):
    assert hasattr(tools_module, name), \
        f"{name} must be re-exported from `serena.tools` for MCP discovery."
    cls = getattr(tools_module, name)
    assert issubclass(cls, Tool)


_EXPECTED_SCALPEL_NAMES = {
    "ScalpelSplitFileTool": "scalpel_split_file",
    "ScalpelExtractTool": "scalpel_extract",
    "ScalpelInlineTool": "scalpel_inline",
    "ScalpelRenameTool": "scalpel_rename",
    "ScalpelImportsOrganizeTool": "scalpel_imports_organize",
    "ScalpelTransactionCommitTool": "scalpel_transaction_commit",
}


@pytest.mark.parametrize("cls_name,expected", list(_EXPECTED_SCALPEL_NAMES.items()))
def test_2a_tool_name_matches_design_spec(cls_name, expected):
    cls = getattr(tools_module, cls_name)
    assert cls.get_name_from_cls() == expected


@pytest.mark.parametrize("cls_name", SCALPEL_2A_TOOLS)
def test_2a_apply_docstring_under_30_words(cls_name):
    cls = getattr(tools_module, cls_name)
    doc = (cls.apply.__doc__ or "").strip()
    headline = doc.split("\n\n", 1)[0]  # contract bit lives in the first paragraph
    word_count = len(headline.split())
    assert word_count <= 30, (
        f"{cls_name}.apply docstring headline must be <= 30 words "
        f"(got {word_count}); §5.4 router-signage rule."
    )


@pytest.mark.parametrize("cls_name", [
    n for n in SCALPEL_2A_TOOLS if n != "ScalpelTransactionCommitTool"
])
def test_2a_apply_invokes_workspace_boundary_guard(cls_name):
    cls = getattr(tools_module, cls_name)
    src = get_apply_source(cls)
    assert "workspace_boundary_guard(" in src, (
        f"{cls_name}.apply must call workspace_boundary_guard() per Q4 §11.8."
    )


def test_2a_iter_subclasses_finds_all_six_tools():
    """The MCP factory walks Tool subclasses; verify the 6 are reachable."""
    discovered: set[str] = set()

    def _walk(cls):
        for sub in cls.__subclasses__():
            discovered.add(sub.__name__)
            _walk(sub)

    _walk(Tool)
    for name in SCALPEL_2A_TOOLS:
        assert name in discovered, (
            f"{name} not reachable via Tool.__subclasses__() walk; "
            f"check that scalpel_facades.py is imported by serena.tools.__init__."
        )
