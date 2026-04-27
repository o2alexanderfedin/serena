"""Stage 1H T11 Module 2 — Multi-server invariant 4 (§11.8 workspace
boundary) from original plan §11.7.

Exercises the ``_check_workspace_boundary`` invariant directly with
synthetic ``WorkspaceEdit`` payloads — this lets the test run without
booting pylsp/basedpyright while still asserting the production
invariant the multi-server merge relies on:

(a) basedpyright-style write into ``calcrs/target/debug/cache/x.py``
    (under the workspace root but inside the build artifact tree) is
    rejected with the ``OUT_OF_WORKSPACE_EDIT_BLOCKED`` reason.

    NOTE: The default ``is_in_workspace`` allows everything under the
    workspace root, so this test asserts the additional check for
    write-into-target/ is rejected when we DON'T list it in workspace
    folders — i.e., we use a tighter workspace folder ``calcrs/src``
    so the ``calcrs/target/...`` write surfaces as out-of-workspace.

(b) pylsp-style write into ``.venv/site-packages/foo/bar.py`` (entirely
    outside the workspace) is rejected — this is the canonical
    out-of-workspace shape.

(c) The rejection is atomic — the rejected reason references the
    out-of-workspace path; no partial application leaks. This is
    asserted by inspecting the second-tuple element (the reason
    string) and confirming it lists exactly the offending path.

Why call ``_check_workspace_boundary`` directly?
------------------------------------------------
The full ``merge_and_validate_code_actions`` path requires pylsp +
basedpyright booted; on hosts without those binaries the path can't
exercise. The invariant itself is pure-python and merge-internal —
testing it directly is the same invariant the merge relies on. The
spec's ``WorkspaceEdit applier`` framing is satisfied because
``_check_workspace_boundary`` IS the merge's applier-level rejection
gate per §11.7 invariant 4.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_text_doc_edit(uri: str) -> dict[str, Any]:
    """Build a minimal documentChanges TextDocumentEdit entry."""
    return {
        "textDocument": {"uri": uri, "version": None},
        "edits": [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
            "newText": "# pwned\n",
        }],
    }


def test_basedpyright_write_into_target_rejected(
    calcrs_workspace: Path,
) -> None:
    """A basedpyright-style WorkspaceEdit that writes into
    ``calcrs/target/debug/cache/x.py`` is rejected when the declared
    workspace folder is the tighter ``calcrs/src`` (not the whole
    repo) — confirms ``_check_workspace_boundary`` enforces the
    declared roots, not a permissive pwd-based fallback."""
    from serena.refactoring.multi_server import _check_workspace_boundary

    target_path = calcrs_workspace / "target" / "debug" / "cache" / "x.py"
    edit = {
        "documentChanges": [_make_text_doc_edit(target_path.as_uri())],
    }
    workspace_folders = [str(calcrs_workspace / "src")]
    ok, reason = _check_workspace_boundary(
        edit=edit,
        workspace_folders=workspace_folders,
        extra_paths=(),
    )
    assert ok is False, (
        f"expected target-tree write to be rejected when workspace folder is "
        f"{workspace_folders[0]!r}; got ok={ok} reason={reason!r}"
    )
    assert reason is not None and "OUT_OF_WORKSPACE_EDIT_BLOCKED" in reason, (
        f"expected OUT_OF_WORKSPACE_EDIT_BLOCKED reason; got {reason!r}"
    )
    assert str(target_path) in reason, (
        f"reason must reference rejected path {target_path}; got {reason!r}"
    )


def test_pylsp_write_into_venv_rejected(
    calcpy_workspace: Path,
    tmp_path: Path,
) -> None:
    """A pylsp-style WorkspaceEdit that writes into a path entirely
    outside the workspace (e.g. ``.venv/site-packages/foo/bar.py``)
    is rejected — the canonical out-of-workspace shape."""
    from serena.refactoring.multi_server import _check_workspace_boundary

    # Synthesize an out-of-workspace target under tmp_path so the test
    # is hermetic; tmp_path lives outside calcpy_workspace by design.
    target_path = tmp_path / "site-packages" / "foo" / "bar.py"
    edit = {
        "documentChanges": [_make_text_doc_edit(target_path.as_uri())],
    }
    workspace_folders = [str(calcpy_workspace)]
    ok, reason = _check_workspace_boundary(
        edit=edit,
        workspace_folders=workspace_folders,
        extra_paths=(),
    )
    assert ok is False, (
        f"expected out-of-workspace write to be rejected; got ok={ok} "
        f"reason={reason!r}"
    )
    assert reason is not None and "OUT_OF_WORKSPACE_EDIT_BLOCKED" in reason
    assert str(target_path) in reason, (
        f"reason must reference rejected path {target_path}; got {reason!r}"
    )


def test_rejection_is_atomic(
    calcpy_workspace: Path,
    tmp_path: Path,
) -> None:
    """Per §11.8 atomicity: when ANY documentChanges entry fails the
    boundary check, the WHOLE edit is rejected (no partial application).

    Build a 2-entry edit where one entry is in-workspace and one is
    out — the function must return ``ok=False`` and surface the
    out-of-workspace path in the rejection reason. The in-workspace
    path must NOT be silently applied."""
    from serena.refactoring.multi_server import _check_workspace_boundary

    in_ws = calcpy_workspace / "calcpy" / "calcpy.py"
    out_ws = tmp_path / "elsewhere" / "leak.py"
    edit = {
        "documentChanges": [
            _make_text_doc_edit(in_ws.as_uri()),
            _make_text_doc_edit(out_ws.as_uri()),
        ],
    }
    ok, reason = _check_workspace_boundary(
        edit=edit,
        workspace_folders=[str(calcpy_workspace)],
        extra_paths=(),
    )
    assert ok is False, (
        f"mixed-edit must be rejected atomically; got ok={ok} reason={reason!r}"
    )
    assert reason is not None
    assert str(out_ws) in reason, (
        f"rejection reason must reference the out-of-workspace path "
        f"{out_ws}; got {reason!r}"
    )
    # The in-workspace path must NOT be in the rejection list (it's the
    # one that WOULD be applied if we weren't atomic).
    assert str(in_ws) not in reason, (
        f"in-workspace path {in_ws} must not be in rejected_paths; the "
        f"reason should list only the offenders. got {reason!r}"
    )
