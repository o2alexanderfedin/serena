"""v1.1 Stream 5 / Leaf 07 Task 1 — `scalpel_convert_to_async` facade tests.

Bypasses the full ``Tool.apply_ex`` lifecycle and constructs the facade
directly with a ``MagicMock(SerenaAgent)``, mirroring Leaf 06's
``test_scalpel_confirm_annotations`` pattern. The MultiServerCoordinator
is not booted — the facade routes through the AST-based helper in
``serena.refactoring.python_async_conversion`` so no pylsp / basedpyright
process is needed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

import pytest

from serena.tools.scalpel_facades import ScalpelConvertToAsyncTool
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.tools_base import Tool
from serena.util.inspection import iter_subclasses


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool(tmp_path: Path) -> ScalpelConvertToAsyncTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = ScalpelConvertToAsyncTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))
    return tool


def test_convert_to_async_marks_def_async_and_propagates_await(
    tmp_path: Path,
) -> None:
    """Happy path — recursive close-over: `caller` becomes async, so
    its `fetch(1)` call site is rewritten to `await fetch(1)`."""
    src = dedent(
        """\
        def fetch(x):
            return x

        async def caller():
            return fetch(1)
        """,
    )
    (tmp_path / "a.py").write_text(src, encoding="utf-8")
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="a.py", symbol="fetch", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    after = (tmp_path / "a.py").read_text(encoding="utf-8")
    assert "async def fetch(x)" in after
    assert "await fetch(1)" in after


def test_convert_to_async_preserves_decorators(tmp_path: Path) -> None:
    """R3 edge case 1 — decorators above the def must be preserved verbatim."""
    (tmp_path / "b.py").write_text(
        "@dec\ndef fetch():\n    return 1\n", encoding="utf-8",
    )
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="b.py", symbol="fetch", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    after = (tmp_path / "b.py").read_text(encoding="utf-8")
    assert after.startswith("@dec\nasync def fetch")


def test_convert_to_async_reports_unwrapped_call_sites(tmp_path: Path) -> None:
    """R3 edge case 2 — sync caller is left alone but counted in summary
    (the recursive close-over rule); the facade exposes the count via
    ``lsp_ops`` so the LLM caller knows to wrap in ``asyncio.run``."""
    src = dedent(
        """\
        def fetch():
            return 1

        def sync_caller():
            return fetch()
        """,
    )
    (tmp_path / "c.py").write_text(src, encoding="utf-8")
    tool = _build_tool(tmp_path)
    payload = json.loads(
        tool.apply(file="c.py", symbol="fetch", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    after = (tmp_path / "c.py").read_text(encoding="utf-8")
    # `sync_caller` is *not* async — its call site stays unwrapped.
    assert "return fetch()" in after
    assert "await fetch()" not in after
    # The lsp_ops metadata should advertise the unwrapped count so the
    # caller can decide what to do.
    summaries = [op for op in payload["lsp_ops"] if op["method"] == "ast.async_conversion"]
    assert summaries, payload["lsp_ops"]


def test_convert_to_async_unknown_symbol_returns_failure(tmp_path: Path) -> None:
    """SYMBOL_NOT_FOUND when the requested name has no `def` in the file."""
    (tmp_path / "d.py").write_text("x = 1\n", encoding="utf-8")
    tool = _build_tool(tmp_path)
    payload = json.loads(
        tool.apply(file="d.py", symbol="fetch", allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    # Failure info lives under ``failure.code`` in the RefactorResult schema.
    assert payload.get("failure", {}).get("code") == "SYMBOL_NOT_FOUND"


def test_convert_to_async_tool_appears_in_iter_subclasses() -> None:
    """Auto-registration via ``iter_subclasses(Tool)`` (Stage 1G mechanism)."""
    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    assert "scalpel_convert_to_async" in discovered


def test_convert_to_async_tool_class_name_is_snake_cased() -> None:
    assert (
        ScalpelConvertToAsyncTool.get_name_from_cls()
        == "scalpel_convert_to_async"
    )
