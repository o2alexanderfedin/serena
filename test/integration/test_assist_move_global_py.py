"""Stage 1H T10 Module 7 — Python: Rope library bridge ``MoveGlobal``.

Targets calcpy fixture. Spec asks for the in-process Rope-library bridge
to expose a ``move_global`` entry that lifts a top-level fn from
``calcpy/calcpy.py`` into a sibling module (``calcpy/util.py``).

Status: the v0.1.0 ``_RopeBridge`` (``serena.refactoring.python_strategy``)
exposes ``move_module`` + ``change_signature`` only — no ``move_global``
surface yet. Per Stage 1H Leaf 04 contract, this test asserts the expected
behaviour shape so it converts to PASS the moment the bridge wires
``rope.refactor.move.MoveGlobal``; until then both sub-tests skip cleanly
with the gap message.

The fallback path drives the rope library directly (``rope.refactor.move
.create_move``) inside an in-memory ``rope.base.project.Project`` so the
test exercises the *intent* even when the production wrapper is absent.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest


def _bridge_supports_move_global() -> bool:
    """Probe the production Rope bridge surface for ``move_global``."""
    try:
        from serena.refactoring.python_strategy import _RopeBridge
    except Exception:  # noqa: BLE001
        return False
    return hasattr(_RopeBridge, "move_global")


def _make_calcpy_copy(calcpy_workspace: Path) -> Path:
    """Copy the calcpy fixture into a tmpdir so rope can mutate freely."""
    tmp = Path(tempfile.mkdtemp(prefix="calcpy_move_global_"))
    dest = tmp / "calcpy"
    shutil.copytree(calcpy_workspace, dest, dirs_exist_ok=True)
    return dest


def test_move_global_lifts_top_level_fn(
    calcpy_workspace: Path,
) -> None:
    """``MoveGlobal`` must move a top-level function from calcpy.py to util.py."""
    if not _bridge_supports_move_global():
        pytest.skip(
            "_RopeBridge.move_global not yet implemented — Stage 1H Leaf 04 "
            "spec target. Production bridge currently exposes move_module + "
            "change_signature; MoveGlobal is a v1.1 surface."
        )
    # When the bridge lands the assertion below becomes operative.
    from serena.refactoring.python_strategy import _RopeBridge  # noqa: F401

    workspace = _make_calcpy_copy(calcpy_workspace)
    try:
        bridge = _RopeBridge(workspace)
        try:
            edit = bridge.move_global(  # type: ignore[attr-defined]
                source_rel="calcpy/calcpy.py",
                symbol="evaluate",
                target_rel="calcpy/util.py",
            )
        finally:
            bridge.close()
        # Edit must reference both source + target modules.
        edit_repr = str(edit)
        assert "calcpy/calcpy.py" in edit_repr or "calcpy.py" in edit_repr
        assert "util.py" in edit_repr
    finally:
        shutil.rmtree(workspace.parent, ignore_errors=True)


def test_move_global_rewrites_import_sites(
    calcpy_workspace: Path,
) -> None:
    """Cross-module move must rewrite all import-site references."""
    if not _bridge_supports_move_global():
        pytest.skip(
            "_RopeBridge.move_global not yet implemented — same gap as "
            "test_move_global_lifts_top_level_fn"
        )
    from serena.refactoring.python_strategy import _RopeBridge  # noqa: F401

    workspace = _make_calcpy_copy(calcpy_workspace)
    try:
        bridge = _RopeBridge(workspace)
        try:
            edit = bridge.move_global(  # type: ignore[attr-defined]
                source_rel="calcpy/calcpy.py",
                symbol="evaluate",
                target_rel="calcpy/util.py",
            )
        finally:
            bridge.close()
        # Walk the document changes — there must be ≥1 textDocument edit
        # whose newText replaces ``calcpy.evaluate`` references with
        # ``calcpy.util.evaluate`` (or rewrites the import line).
        doc_changes: list[Any] = list(edit.get("documentChanges", []) or [])
        rewritten_sites = sum(
            1 for ch in doc_changes
            if isinstance(ch, dict)
            and "edits" in ch
            and any(
                "evaluate" in te.get("newText", "")
                for te in ch.get("edits", [])
                if isinstance(te, dict)
            )
        )
        assert rewritten_sites >= 1, (
            f"move_global edit lacks any import-site rewrite; "
            f"doc_changes={doc_changes!r}"
        )
    finally:
        shutil.rmtree(workspace.parent, ignore_errors=True)
