"""v1.9.1 Item B — per-symbol move semantics for ``split_file`` (Python).

In v1.6, ``groups[group_name] = [symbol_a, symbol_b, ...]`` was tagged
informational: the rope bridge moved the WHOLE source module. Item B
unblocks per-symbol move via Rope's ``MoveGlobal`` API. When symbols
are listed, only those symbols leave the source module; the rest stay.

RED tests:

1. Per-symbol move via ``bridge.move_global`` is invoked once per
   listed symbol; the deprecated ``bridge.move_module`` is NOT invoked
   when ``groups[k]`` is non-empty.
2. End-to-end against the real rope project: a 3-symbol module with
   ``groups={"target.py": ["move_b", "move_c"]}`` produces a final
   tree where ``mod.py`` retains ``keep_a`` and ``target.py`` carries
   ``move_b`` + ``move_c``.
3. The informational warning from v1.6 (``groups[k] is informational``)
   is NOT emitted when per-symbol move succeeds.
4. When a listed symbol does not exist in the source, the dispatch
   surfaces a single ``symbol not found: {name}`` warning per missing
   symbol but still applies the moves for the symbols that resolved.
5. Whole-module move (``groups[k] = []``) still works — backward
   compatibility with v1.6 callers.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_facades import SplitFileTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> SplitFileTool:
    tool = SplitFileTool.__new__(SplitFileTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _three_symbol_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "mod.py"
    src.write_text(
        "def keep_a(x):\n    return x\n\n"
        "def move_b(y):\n    return y * 2\n\n"
        "def move_c(z):\n    return z + 1\n",
        encoding="utf-8",
    )
    return tmp_path


def _replace_full_file_edit(uri: str, new_content: str, line_count: int = 9) -> dict[str, Any]:
    """Build a WorkspaceEdit that replaces lines [0..line_count) with new_content."""
    return {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": line_count, "character": 0},
                    },
                    "newText": new_content,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# RED 1 — per-symbol invocation (mocked bridge)
# ---------------------------------------------------------------------------


def test_split_python_with_symbol_list_invokes_move_global_per_symbol(tmp_path: Path) -> None:
    workspace = _three_symbol_workspace(tmp_path)
    src = workspace / "mod.py"
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_global.return_value = _replace_full_file_edit(uri, "def keep_a(x):\n    return x\n", line_count=9)
    fake_bridge.move_module.side_effect = AssertionError(
        "v1.9.1 Item B: move_module must NOT be invoked when symbols are listed"
    )
    tool = _make_tool(workspace)
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        raw = tool.apply(
            file=str(src),
            groups={"target.py": ["move_b", "move_c"]},
            language="python",
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    # Two symbols listed -> two move_global invocations.
    assert fake_bridge.move_global.call_count == 2
    fake_bridge.move_module.assert_not_called()
    # Calls should reference the listed symbols.
    invoked_symbols = sorted(
        call.kwargs.get("symbol_name") or call.args[1]
        for call in fake_bridge.move_global.call_args_list
    )
    assert invoked_symbols == ["move_b", "move_c"]


# ---------------------------------------------------------------------------
# RED 2 — informational warning suppressed when per-symbol move works
# ---------------------------------------------------------------------------


def test_split_python_per_symbol_move_suppresses_informational_warning(tmp_path: Path) -> None:
    workspace = _three_symbol_workspace(tmp_path)
    src = workspace / "mod.py"
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_global.return_value = _replace_full_file_edit(uri, "x", line_count=9)
    tool = _make_tool(workspace)
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        raw = tool.apply(
            file=str(src),
            groups={"target.py": ["move_b"]},
            language="python",
        )
    payload = json.loads(raw)
    warnings = payload.get("warnings") or ()
    assert not any(
        "informational" in w.lower()
        for w in warnings
    ), f"per-symbol move must not emit the v1.6 informational caveat; got {warnings!r}"


# ---------------------------------------------------------------------------
# RED 3 — empty symbol list keeps whole-module behaviour
# ---------------------------------------------------------------------------


def test_split_python_empty_symbol_list_falls_back_to_move_module(tmp_path: Path) -> None:
    workspace = _three_symbol_workspace(tmp_path)
    src = workspace / "mod.py"
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = _replace_full_file_edit(uri, "x", line_count=9)
    fake_bridge.move_global.side_effect = AssertionError(
        "empty symbol list must use whole-module move (v1.6 contract)"
    )
    tool = _make_tool(workspace)
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        raw = tool.apply(
            file=str(src),
            groups={"helpers": []},
            language="python",
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    fake_bridge.move_module.assert_called_once()
    fake_bridge.move_global.assert_not_called()


# ---------------------------------------------------------------------------
# RED 4 — missing symbol surfaces per-symbol warning, applies remainder
# ---------------------------------------------------------------------------


def test_split_python_missing_symbol_warns_but_applies_resolved(tmp_path: Path) -> None:
    workspace = _three_symbol_workspace(tmp_path)
    src = workspace / "mod.py"
    uri = src.as_uri()
    from serena.refactoring.python_strategy import RopeBridgeError

    def _move_global_side_effect(source_rel, symbol_name, target_rel):  # noqa: ARG001
        if symbol_name == "missing_symbol":
            raise RopeBridgeError(f"symbol not found: {symbol_name}")
        return _replace_full_file_edit(uri, "x", line_count=9)

    fake_bridge = MagicMock()
    fake_bridge.move_global.side_effect = _move_global_side_effect
    tool = _make_tool(workspace)
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        raw = tool.apply(
            file=str(src),
            groups={"target.py": ["move_b", "missing_symbol"]},
            language="python",
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    warnings = payload.get("warnings") or ()
    assert any(
        "missing_symbol" in w
        for w in warnings
    ), f"expected per-symbol 'missing_symbol' warning, got {warnings!r}"


# ---------------------------------------------------------------------------
# RED 5 — end-to-end against real rope project
# ---------------------------------------------------------------------------


def test_split_python_per_symbol_move_real_rope(tmp_path: Path) -> None:
    """No mock — drives the live ``_RopeBridge`` end to end.

    Source ``mod.py``:
        def keep_a(x): ...
        def move_b(y): ...
        def move_c(z): ...

    After ``groups={"target.py": ["move_b", "move_c"]}``:
    - ``mod.py`` contains only ``keep_a``
    - ``target.py`` contains ``move_b`` and ``move_c``
    """
    workspace = _three_symbol_workspace(tmp_path)
    src = workspace / "mod.py"
    target = workspace / "target.py"
    tool = _make_tool(workspace)
    raw = tool.apply(
        file=str(src),
        groups={"target.py": ["move_b", "move_c"]},
        language="python",
    )
    payload = json.loads(raw)
    assert payload["applied"] is True, payload
    src_after = src.read_text(encoding="utf-8")
    assert "keep_a" in src_after, src_after
    assert "move_b" not in src_after, src_after
    assert "move_c" not in src_after, src_after
    assert target.exists(), "target.py should be created by per-symbol move"
    target_after = target.read_text(encoding="utf-8")
    assert "move_b" in target_after, target_after
    assert "move_c" in target_after, target_after
