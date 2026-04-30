"""v1.6 PR 4 / Plan 3 — Fix scalpel_split_file._split_python apply-to-disk.

RED tests:
1. ``test_split_python_writes_to_disk`` — ``_build_python_rope_bridge`` is
   patched to return a fake whose ``move_module`` returns a real
   ``WorkspaceEdit``; ``tool.apply(..., dry_run=False)`` must mutate the
   source file on disk.
2. ``test_split_python_records_real_snapshot_in_checkpoint`` — same setup;
   the checkpoint store's snapshot for the touched URI must equal the
   pre-edit content (validates Plan 1 wired into the python branch).
3. ``test_split_python_dry_run_does_not_apply`` — same setup with
   ``dry_run=True``; disk must be untouched.
4. ``test_split_python_groups_keys_only_emits_warning_when_values_present``
   — caller passes ``groups={"helpers": ["add"]}`` (non-empty symbol list);
   ``RefactorResult.warnings`` must mention the v1.6 informational caveat.

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md  Plan 3
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_facades import ScalpelSplitFileTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> ScalpelSplitFileTool:
    tool = ScalpelSplitFileTool.__new__(ScalpelSplitFileTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "calcpy.py"
    src.write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_replace_alpha_edit(uri: str) -> dict[str, Any]:
    """Build a WorkspaceEdit (changes shape) that replaces the first 14 chars
    of the file with ``'def aaa(): pass\\n'``. The exact size doesn't matter
    — what matters is that the post-edit bytes differ from the pre-edit
    bytes so the test can assert disk mutation."""
    return {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 14},
                    },
                    "newText": "def aaa(): pass",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# RED 1 — _split_python writes to disk when dry_run=False
# ---------------------------------------------------------------------------


def test_split_python_writes_to_disk(tmp_path: Path) -> None:
    workspace = _python_workspace(tmp_path)
    src = workspace / "calcpy.py"
    pre_edit = src.read_text(encoding="utf-8")
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = _make_replace_alpha_edit(uri)
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
    assert payload["checkpoint_id"]
    # Disk MUST be mutated.
    post_edit = src.read_text(encoding="utf-8")
    assert post_edit != pre_edit
    assert post_edit.startswith("def aaa(): pass")


# ---------------------------------------------------------------------------
# RED 2 — checkpoint records honest pre-edit snapshot
# ---------------------------------------------------------------------------


def test_split_python_records_real_snapshot_in_checkpoint(tmp_path: Path) -> None:
    workspace = _python_workspace(tmp_path)
    src = workspace / "calcpy.py"
    pre_edit = src.read_text(encoding="utf-8")
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = _make_replace_alpha_edit(uri)
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
    cid = payload["checkpoint_id"]
    assert cid
    ckpt = ScalpelRuntime.instance().checkpoint_store().get(cid)
    assert ckpt is not None
    assert ckpt.snapshot.get(uri) == pre_edit


# ---------------------------------------------------------------------------
# RED 3 — dry_run skips apply
# ---------------------------------------------------------------------------


def test_split_python_dry_run_does_not_apply(tmp_path: Path) -> None:
    workspace = _python_workspace(tmp_path)
    src = workspace / "calcpy.py"
    pre_edit = src.read_text(encoding="utf-8")
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = _make_replace_alpha_edit(uri)
    tool = _make_tool(workspace)
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        raw = tool.apply(
            file=str(src),
            groups={"helpers": []},
            language="python",
            dry_run=True,
        )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["preview_token"]
    # Disk untouched.
    assert src.read_text(encoding="utf-8") == pre_edit


# ---------------------------------------------------------------------------
# RED 4 (v1.9.1 Item B) — non-empty groups[*] symbol list dispatches to
# per-symbol move via the rope bridge's ``move_global``. The v1.6
# informational warning is gone — the bridge now honours per-symbol
# selection. ``test_v19_b_split_python_per_symbol_move`` covers the
# full v1.9.1 contract; this regression test pins the v1.6 wire so the
# informational warning does NOT come back.
# ---------------------------------------------------------------------------


def test_split_python_groups_keys_with_values_routes_to_per_symbol_move(
    tmp_path: Path,
) -> None:
    workspace = _python_workspace(tmp_path)
    src = workspace / "calcpy.py"
    uri = src.as_uri()
    fake_bridge = MagicMock()
    fake_bridge.move_global.return_value = _make_replace_alpha_edit(uri)
    fake_bridge.move_module.side_effect = AssertionError(
        "v1.9.1: non-empty symbol list must route to move_global, not move_module"
    )
    tool = _make_tool(workspace)
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        raw = tool.apply(
            file=str(src),
            groups={"helpers": ["add"]},
            language="python",
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    fake_bridge.move_global.assert_called_once()
    fake_bridge.move_module.assert_not_called()
    warnings = payload.get("warnings") or ()
    assert not any(
        "informational" in w.lower() for w in warnings
    ), f"v1.6 informational warning must not return; got {warnings!r}"
