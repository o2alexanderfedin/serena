"""v1.5 G4-9 — imports_organize honors add_missing / remove_unused / reorder
(HI-10 + part of HI-13).

Acid tests:
  * remove_unused=True (only) dispatches the
    `source.organizeImports.removeUnused` sub-kind ONLY; no `sortImports`,
    no `quickfix.import`. Real-disk read confirms the unused import is
    removed while the others persist.
  * add_missing+remove_unused+reorder=True dispatches all three sub-kinds.
  * All three flags False → no_op (no LSP dispatch).
  * The LSP request range is no longer (0,0)→(0,0); compute_file_range
    brackets the whole file (closes the imports_organize site of HI-13).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelImportsOrganizeTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "main.py"
    src.write_text(
        "import sys\n"
        "import os\n"
        "import json  # unused\n"
        "print(sys.version, os.path.exists)\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_tool(project_root: Path) -> Any:
    tool = ScalpelImportsOrganizeTool.__new__(ScalpelImportsOrganizeTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, kind: str, provenance: str = "ruff"):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = f"Apply {kind}"
    a.kind = kind
    a.is_preferred = False
    a.provenance = provenance
    return a


def test_remove_unused_only_dispatches_remove_unused_kind(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        only = kw.get("only") or []
        if only and "removeUnused" in only[0]:
            return [_action("ruff:1", only[0])]
        return []

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {src.as_uri(): [{
        "range": {"start": {"line": 2, "character": 0},
                  "end": {"line": 3, "character": 0}},
        "newText": "",
    }]}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            files=[str(src)],
            add_missing=False,
            remove_unused=True,
            reorder=False,
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    only_values = [c.get("only") for c in captured]
    # Exactly one dispatch with the remove-unused kind:
    assert any("removeUnused" in str(o) for o in only_values), only_values
    # No dispatch for sortImports or quickfix.import:
    assert not any("sortImports" in str(o) for o in only_values), only_values
    assert not any("quickfix.import" in str(o) for o in only_values), only_values

    # Real-disk acid test: unused json import gone, others preserved:
    body = src.read_text(encoding="utf-8")
    assert "import json" not in body
    assert "import sys" in body
    assert "import os" in body


def test_all_three_flags_dispatch_all_three_kinds(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[str] = []

    async def _actions(**kw):
        only = (kw.get("only") or [""])[0]
        captured.append(only)
        return [_action("a:1", only)]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        tool.apply(
            files=[str(src)],
            add_missing=True,
            remove_unused=True,
            reorder=True,
            language="python",
        )
    # All three sub-kinds dispatched:
    assert any("removeUnused" in c for c in captured), captured
    assert any("sortImports" in c for c in captured), captured
    assert any("quickfix.import" in c for c in captured), captured


def test_no_flags_is_no_op(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[str] = []

    async def _actions(**kw):
        captured.append((kw.get("only") or [""])[0])
        return []

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            files=[str(src)],
            add_missing=False,
            remove_unused=False,
            reorder=False,
            language="python",
        )
    payload = json.loads(out)
    assert payload["no_op"] is True
    assert captured == []


def test_dispatch_uses_real_file_range_not_zero_zero(python_workspace):
    """Closes the imports_organize site of HI-13: the LSP request range
    brackets the whole file via compute_file_range, not (0,0)→(0,0)."""
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        return [_action("a:1", (kw.get("only") or [""])[0])]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        tool.apply(
            files=[str(src)],
            add_missing=False,
            remove_unused=True,
            reorder=False,
            language="python",
        )
    assert captured
    end = captured[0].get("end") or {}
    assert (end.get("line"), end.get("character")) != (0, 0), captured
