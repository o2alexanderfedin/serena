"""v1.5 G2 — dry_run safety honor on expand_macro + verify_after_refactor.

Acid test: when dry_run=True, the coord's expand_macro / fetch_runnables /
run_flycheck methods MUST NOT be called. The pre-G2 code calls them and
ignores the dry_run flag entirely (HI-12 safety violation).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    ScalpelExpandMacroTool,
    ScalpelVerifyAfterRefactorTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text("fn main() { println!(\"hi\"); }\n")
    return tmp_path


def _make_expand(project_root: Path) -> ScalpelExpandMacroTool:
    tool = ScalpelExpandMacroTool.__new__(ScalpelExpandMacroTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _make_verify(project_root: Path) -> ScalpelVerifyAfterRefactorTool:
    tool = ScalpelVerifyAfterRefactorTool.__new__(ScalpelVerifyAfterRefactorTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_expand_macro_dry_run_does_not_call_lsp(rust_workspace):
    tool = _make_expand(rust_workspace)
    fake_coord = MagicMock()
    fake_coord.expand_macro = MagicMock()  # If called → assertion below fails.

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(rust_workspace / "lib.rs"),
            position={"line": 0, "character": 12},
            dry_run=True,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["no_op"] is False  # preview, not no-op
    assert payload["preview_token"] is not None
    fake_coord.expand_macro.assert_not_called()


def test_expand_macro_no_dry_run_calls_lsp(rust_workspace):
    """Counter-test: ensure we didn't accidentally short-circuit
    the non-dry_run path."""
    tool = _make_expand(rust_workspace)
    fake_coord = MagicMock()

    async def _fake_expand(**kw):
        return {"name": "println", "expansion": "// expansion"}

    fake_coord.expand_macro = _fake_expand

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(rust_workspace / "lib.rs"),
            position={"line": 0, "character": 12},
            dry_run=False,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_verify_after_refactor_dry_run_does_not_call_lsp(rust_workspace):
    tool = _make_verify(rust_workspace)
    fake_coord = MagicMock()
    fake_coord.fetch_runnables = MagicMock()
    fake_coord.run_flycheck = MagicMock()

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(rust_workspace / "lib.rs"),
            dry_run=True,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None
    fake_coord.fetch_runnables.assert_not_called()
    fake_coord.run_flycheck.assert_not_called()


def test_verify_after_refactor_no_dry_run_calls_lsp(rust_workspace):
    tool = _make_verify(rust_workspace)
    fake_coord = MagicMock()

    async def _fake_runnables(**kw):
        return []

    async def _fake_flycheck(**kw):
        return {"diagnostics": []}

    fake_coord.fetch_runnables = _fake_runnables
    fake_coord.run_flycheck = _fake_flycheck

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(rust_workspace / "lib.rs"),
            dry_run=False,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
