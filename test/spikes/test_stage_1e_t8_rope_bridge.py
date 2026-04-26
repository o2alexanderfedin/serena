"""T8 — Rope library bridge (rope==1.14.0; specialist-python.md §10 row 'MoveModule')."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_rope_bridge_imports() -> None:
    from serena.refactoring.python_strategy import _RopeBridge, RopeBridgeError  # noqa: F401

    del _RopeBridge
    del RopeBridgeError


def test_rope_bridge_move_module_returns_workspace_edit(tmp_path: Path) -> None:
    """MoveModule renames a .py file and rewrites importers — typed WorkspaceEdit out."""
    from serena.refactoring.python_strategy import _RopeBridge

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("def hello() -> int:\n    return 1\n")
    (pkg / "user.py").write_text("from pkg.a import hello\nprint(hello())\n")

    bridge = _RopeBridge(project_root=tmp_path)
    try:
        edit = bridge.move_module(source_rel="pkg/a.py", target_rel="pkg/b.py")
    finally:
        bridge.close()

    # WorkspaceEdit shape: documentChanges (preferred) OR changes mapping.
    assert "documentChanges" in edit or "changes" in edit, edit
    # At minimum, the target file appears in the edit (rename op).
    payload = str(edit)
    assert "pkg/b.py" in payload or "b.py" in payload, payload


def test_rope_bridge_change_signature_typed_inputs(tmp_path: Path) -> None:
    """ChangeSignature takes typed Pydantic input; raises RopeBridgeError on bad symbol."""
    from serena.refactoring.python_strategy import (
        ChangeSignatureSpec,
        RopeBridgeError,
        _RopeBridge,
    )

    (tmp_path / "x.py").write_text("def f(a, b): return a + b\n")
    bridge = _RopeBridge(project_root=tmp_path)
    try:
        with pytest.raises(RopeBridgeError):
            bridge.change_signature(
                ChangeSignatureSpec(
                    file_rel="x.py",
                    symbol_offset=99999,  # past EOF — Rope cannot resolve
                    new_parameters=["a", "b", "c=0"],
                )
            )
    finally:
        bridge.close()
