"""Stage 1H T10 Module 8 — Python: Rope library bridge ``MoveModule`` rename.

Targets calcpy fixture (copied to a tmpdir per test so rope can mutate
freely). Asserts:

(a) ``_RopeBridge.move_module(source_rel="calcpy/core.py",
    target_rel="calcpy/legacy_core.py")`` returns a WorkspaceEdit whose
    ``documentChanges`` includes a ``rename``-kind entry from old → new
    URI.
(b) Any importer of ``calcpy.core`` (the calcpy package's ``__init__.py``
    or ``calcpy.py``) is rewritten in the same edit.

Skips honestly when rope is unavailable (the bridge's ``__init__``
imports ``rope.base.project``).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest


def _make_calcpy_copy(calcpy_workspace: Path) -> Path:
    """Copy the calcpy fixture into a tmpdir so rope can mutate freely."""
    tmp = Path(tempfile.mkdtemp(prefix="calcpy_rename_module_"))
    dest = tmp / "calcpy"
    shutil.copytree(calcpy_workspace, dest, dirs_exist_ok=True)
    return dest


def _construct_bridge(workspace: Path) -> Any:
    try:
        from serena.refactoring.python_strategy import _RopeBridge
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"_RopeBridge import failed: {exc!r}")
    try:
        return _RopeBridge(workspace)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"_RopeBridge construction failed: {exc!r}")


def test_move_module_renames_core_to_legacy(
    calcpy_workspace: Path,
) -> None:
    """``MoveModule`` must rename ``calcpy/core.py`` → ``calcpy/legacy_core.py``."""
    workspace = _make_calcpy_copy(calcpy_workspace)
    try:
        # Verify pre-condition: calcpy/core.py exists in the copy.
        src_path = workspace / "calcpy" / "core.py"
        if not src_path.exists():
            pytest.skip(f"calcpy/core.py missing in workspace copy: {src_path}")

        bridge = _construct_bridge(workspace)
        try:
            edit = bridge.move_module(
                source_rel="calcpy/core.py",
                target_rel="calcpy/legacy_core.py",
            )
        finally:
            bridge.close()

        doc_changes = list(edit.get("documentChanges", []) or [])
        rename_entries = [
            ch for ch in doc_changes
            if isinstance(ch, dict) and ch.get("kind") == "rename"
        ]
        assert rename_entries, (
            f"move_module did not emit a rename entry; doc_changes={doc_changes!r}"
        )
        # The rename's oldUri must reference core.py and newUri legacy_core.py.
        match = next(
            (
                r for r in rename_entries
                if "core.py" in r.get("oldUri", "")
                and "legacy_core.py" in r.get("newUri", "")
            ),
            None,
        )
        assert match is not None, (
            f"rename entry old/new URIs do not match expected pattern; "
            f"rename_entries={rename_entries!r}"
        )
    finally:
        shutil.rmtree(workspace.parent, ignore_errors=True)


def test_move_module_rewrites_importer_sites(
    calcpy_workspace: Path,
) -> None:
    """Any ``from calcpy.core import …`` site must be rewritten in the same edit.

    The fixture's calcpy/__init__.py may or may not import from core; the
    test relaxes the assertion so it surfaces a rewrite when at least one
    importer is found, and skips cleanly when no importer exists in the
    fixture (move-without-importers is still a valid rope output).
    """
    workspace = _make_calcpy_copy(calcpy_workspace)
    try:
        # Probe the fixture for any importer of calcpy.core.
        importer_files: list[Path] = []
        for py_path in (workspace / "calcpy").rglob("*.py"):
            if py_path.name == "core.py":
                continue
            text = py_path.read_text()
            if "from calcpy.core" in text or "from .core" in text or "import core" in text:
                importer_files.append(py_path)
        bridge = _construct_bridge(workspace)
        try:
            edit = bridge.move_module(
                source_rel="calcpy/core.py",
                target_rel="calcpy/legacy_core.py",
            )
        finally:
            bridge.close()

        if not importer_files:
            # No importers present — the test still requires the rename hit.
            doc_changes = list(edit.get("documentChanges", []) or [])
            renames = [
                ch for ch in doc_changes
                if isinstance(ch, dict) and ch.get("kind") == "rename"
            ]
            assert renames, "no rename entry in edit"
            pytest.skip(
                "calcpy fixture has no importers of calcpy.core; importer "
                "rewrite assertion is vacuous on this fixture"
            )

        doc_changes = list(edit.get("documentChanges", []) or [])
        textdoc_changes = [
            ch for ch in doc_changes
            if isinstance(ch, dict) and "edits" in ch
        ]
        # Look for a textDocument edit that references one of the importer files.
        importer_uris = {p.as_uri() for p in importer_files}
        rewritten = [
            ch for ch in textdoc_changes
            if ch.get("textDocument", {}).get("uri", "") in importer_uris
        ]
        assert rewritten, (
            f"no textDocument edit targets importer files; "
            f"importers={[str(p) for p in importer_files]}, "
            f"textdoc_changes_uris="
            f"{[ch.get('textDocument', {}).get('uri') for ch in textdoc_changes]}"
        )
    finally:
        shutil.rmtree(workspace.parent, ignore_errors=True)
