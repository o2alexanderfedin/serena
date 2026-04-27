"""Reproduce the inspect.getsource(cls.apply) flake (D-debt.md §2).

inspect.getsource consults linecache, which is unstable across xdist
workers and pyc-only loads. This test calls the introspection path 100
times per facade class and asserts identical, non-empty output.
"""
from __future__ import annotations

import inspect

import pytest

import serena.tools as tools_module

# Verified union of classes the 6 spike sites inspect (t1/t2/t3/t4/t5: 4 each;
# 2A registry smoke: SCALPEL_2A_TOOLS minus TransactionCommit = 5).
_FACADE_NAMES = (
    "ScalpelConvertModuleLayoutTool", "ScalpelChangeVisibilityTool",
    "ScalpelTidyStructureTool", "ScalpelChangeTypeShapeTool",
    "ScalpelChangeReturnTypeTool", "ScalpelCompleteMatchArmsTool",
    "ScalpelExtractLifetimeTool", "ScalpelExpandGlobImportsTool",
    "ScalpelGenerateTraitImplScaffoldTool", "ScalpelGenerateMemberTool",
    "ScalpelExpandMacroTool", "ScalpelVerifyAfterRefactorTool",
    "ScalpelConvertToMethodObjectTool", "ScalpelLocalToFieldTool",
    "ScalpelUseFunctionTool", "ScalpelIntroduceParameterTool",
    "ScalpelGenerateFromUndefinedTool", "ScalpelAutoImportSpecializedTool",
    "ScalpelFixLintsTool", "ScalpelIgnoreDiagnosticTool",
    "ScalpelSplitFileTool", "ScalpelExtractTool", "ScalpelInlineTool",
    "ScalpelRenameTool", "ScalpelImportsOrganizeTool",
)


@pytest.mark.parametrize("cls_name", _FACADE_NAMES)
def test_apply_source_is_stable_across_repeated_calls(cls_name: str) -> None:
    cls = getattr(tools_module, cls_name)
    samples = [inspect.getsource(cls.apply) for _ in range(100)]
    first = samples[0]
    assert first, f"{cls_name}.apply source must be non-empty"
    assert all(s == first for s in samples), (
        f"{cls_name}.apply source non-deterministic across 100 calls"
    )
    assert "workspace_boundary_guard(" in first


def test_every_inspected_facade_has_wrapped_source_attribute() -> None:
    """Every facade Tool inspected by the 6 spike sites must opt in."""
    for name in _FACADE_NAMES:
        cls = getattr(tools_module, name)
        captured = getattr(cls.apply, "__wrapped_source__", None)
        assert isinstance(captured, str) and captured, (
            f"{name}.apply must carry __wrapped_source__"
        )
        assert "workspace_boundary_guard(" in captured
