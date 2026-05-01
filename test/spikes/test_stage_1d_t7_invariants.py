"""T7 — §11.7 four invariants on merged code actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from serena.refactoring.multi_server import (
    MultiServerCoordinator,
    _check_apply_clean,
    _check_syntactic_validity,
    _check_workspace_boundary,
)


def _edit(uri: str, sl: int, sc: int, el: int, ec: int, txt: str) -> dict:
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": 7},
                "edits": [
                    {"range": {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}, "newText": txt}
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Invariant 1 — apply-clean (server-tracked version match).
# ---------------------------------------------------------------------------

def test_apply_clean_passes_when_versions_match() -> None:
    edit = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    versions = {"file:///x.py": 7}
    ok, reason = _check_apply_clean(edit, versions)
    assert ok is True
    assert reason is None


def test_apply_clean_fails_when_versions_mismatch() -> None:
    edit = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    versions = {"file:///x.py": 9}
    ok, reason = _check_apply_clean(edit, versions)
    assert ok is False
    assert "STALE_VERSION" in reason  # type: ignore[arg-type]


def test_apply_clean_skips_when_edit_version_is_none() -> None:
    """A None ``textDocument.version`` means version-agnostic per LSP."""
    edit = {
        "documentChanges": [
            {"textDocument": {"uri": "file:///x.py", "version": None},
             "edits": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}}, "newText": "h"}]}
        ]
    }
    versions = {"file:///x.py": 9}
    ok, _ = _check_apply_clean(edit, versions)
    assert ok is True


# ---------------------------------------------------------------------------
# Invariant 2 — syntactic validity via ast.parse on the post-apply text.
# ---------------------------------------------------------------------------

def test_syntactic_validity_passes_on_valid_python(tmp_path: Path) -> None:
    src = tmp_path / "v.py"
    src.write_text("x = 1\n", encoding="utf-8")
    edit = _edit(src.as_uri(), 0, 0, 1, 0, "y = 2\n")
    ok, reason = _check_syntactic_validity(edit)
    assert ok is True
    assert reason is None


def test_syntactic_validity_fails_on_broken_python(tmp_path: Path) -> None:
    src = tmp_path / "b.py"
    src.write_text("x = 1\n", encoding="utf-8")
    edit = _edit(src.as_uri(), 0, 0, 1, 0, "def (\n")  # syntactically broken
    ok, reason = _check_syntactic_validity(edit)
    assert ok is False
    assert "SyntaxError" in reason  # type: ignore[arg-type]


def test_syntactic_validity_skips_non_python_files(tmp_path: Path) -> None:
    src = tmp_path / "v.txt"
    src.write_text("x = 1\n", encoding="utf-8")
    edit = _edit(src.as_uri(), 0, 0, 1, 0, "garbled (((\n")
    ok, _ = _check_syntactic_validity(edit)
    assert ok is True  # not .py → invariant doesn't apply


# ---------------------------------------------------------------------------
# Invariant 4 — workspace-boundary path filter (§11.8).
# ---------------------------------------------------------------------------

def test_workspace_boundary_passes_in_workspace(tmp_path: Path) -> None:
    f = tmp_path / "in.py"
    f.write_text("x = 1\n", encoding="utf-8")
    edit = _edit(f.as_uri(), 0, 0, 0, 0, "")
    ok, reason = _check_workspace_boundary(edit, workspace_folders=[str(tmp_path)], extra_paths=())
    assert ok is True
    assert reason is None


def test_workspace_boundary_fails_outside(tmp_path: Path) -> None:
    edit = _edit("file:///etc/passwd", 0, 0, 0, 0, "evil")
    ok, reason = _check_workspace_boundary(edit, workspace_folders=[str(tmp_path)], extra_paths=())
    assert ok is False
    assert reason is not None
    assert "OUT_OF_WORKSPACE_EDIT_BLOCKED" in reason
    assert "/etc/passwd" in reason


def test_workspace_boundary_create_file_uri_checked(tmp_path: Path) -> None:
    """CreateFile.uri must also be inside the workspace."""
    edit = {
        "documentChanges": [
            {"kind": "create", "uri": "file:///tmp/random/outside.py"},
        ]
    }
    ok, _ = _check_workspace_boundary(edit, workspace_folders=[str(tmp_path)], extra_paths=())
    assert ok is False


def test_workspace_boundary_rename_old_and_new_checked(tmp_path: Path) -> None:
    in_ws = (tmp_path / "in.py").as_uri()
    edit = {
        "documentChanges": [
            {"kind": "rename", "oldUri": in_ws, "newUri": "file:///tmp/outside.py"},
        ]
    }
    ok, _ = _check_workspace_boundary(edit, workspace_folders=[str(tmp_path)], extra_paths=())
    assert ok is False


def test_workspace_boundary_extra_paths_allowlist(tmp_path: Path) -> None:
    other = tmp_path.parent / "other_root"
    other.mkdir(exist_ok=True)
    edit = _edit((other / "x.py").as_uri(), 0, 0, 0, 0, "")
    ok, _ = _check_workspace_boundary(
        edit,
        workspace_folders=[str(tmp_path)],
        extra_paths=(str(other),),
    )
    assert ok is True


# ---------------------------------------------------------------------------
# merge_and_validate_code_actions — wrapping integration.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merge_and_validate_drops_invariant_failures(fake_pool, tmp_path: Path):
    in_ws = tmp_path / "ok.py"
    in_ws.write_text("x = 1\n", encoding="utf-8")
    out_of_ws_uri = "file:///etc/passwd"
    fake_pool["ruff"].code_actions = [
        {"title": "Organize", "kind": "source.organizeImports.ruff",
         "edit": _edit(out_of_ws_uri, 0, 0, 0, 0, "evil")}
    ]
    fake_pool["pylsp-rope"].code_actions = [
        {"title": "Organize", "kind": "source.organizeImports",
         "edit": _edit(in_ws.as_uri(), 0, 0, 1, 0, "x = 2\n")}
    ]
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    auto_apply, surfaced = await coord.merge_and_validate_code_actions(
        file=str(in_ws),
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
        workspace_folders=[str(tmp_path)],
        document_versions={in_ws.as_uri(): 7},
    )
    # ruff would have won on priority but FAILED invariant 4 → dropped
    # from auto_apply; pylsp-rope wins by elimination.
    assert [a.provenance for a in auto_apply] == ["pylsp-rope"]
    surfaced_provs = {a.provenance for a in surfaced}
    assert "ruff" in surfaced_provs
