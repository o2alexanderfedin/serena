"""Stage 1H T11 Module 3 — Multi-server invariant 1 (apply-clean /
STALE_VERSION) from original plan §11.7.

Exercises the merge-internal ``_check_apply_clean`` helper directly with
synthetic ``WorkspaceEdit`` payloads. ``merge_and_validate_code_actions``
calls this helper before promoting any candidate to ``auto_apply``;
when the textDocument version on the edit doesn't match the
server-tracked version, the candidate is dropped with a STALE_VERSION
reason and never applied to disk.

(a) When the edit's ``textDocument.version`` differs from the
    coordinator's tracked version for that URI, the helper returns
    ``ok=False`` with a reason starting with ``STALE_VERSION:``.

(b) When ``ok=False``, the edit is dropped from auto-apply — we assert
    the reason carries enough provenance (uri, edit_version,
    tracked) for the agent to triage.

Why call ``_check_apply_clean`` directly?
-----------------------------------------
Same rationale as module 2: the full merge-and-validate pipeline needs
pylsp + basedpyright booted. The invariant itself is pure-python and
merge-internal; testing it directly asserts the same invariant the
multi-server path relies on.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_versioned_text_doc_edit(uri: str, version: int | None) -> dict[str, Any]:
    """Build a minimal documentChanges TextDocumentEdit with explicit version."""
    return {
        "textDocument": {"uri": uri, "version": version},
        "edits": [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
            "newText": "# late edit\n",
        }],
    }


def test_stale_version_rejected_with_reason(
    calcpy_workspace: Path,
) -> None:
    """A WorkspaceEdit whose textDocument.version mismatches the
    coordinator's tracked version must be rejected with a
    STALE_VERSION reason that carries uri + edit_version + tracked
    for triage."""
    from serena.refactoring.multi_server import _check_apply_clean

    src = calcpy_workspace / "calcpy" / "calcpy.py"
    uri = src.as_uri()
    edit = {
        "documentChanges": [_make_versioned_text_doc_edit(uri, version=3)],
    }
    document_versions = {uri: 7}  # tracked version is newer
    ok, reason = _check_apply_clean(
        edit=edit,
        document_versions=document_versions,
    )
    assert ok is False, (
        f"expected stale-version edit to be rejected; got ok={ok} reason={reason!r}"
    )
    assert reason is not None and reason.startswith("STALE_VERSION:"), (
        f"reason must be tagged STALE_VERSION:; got {reason!r}"
    )
    assert "edit_version=3" in reason and "tracked=7" in reason, (
        f"reason must carry edit_version + tracked for triage; got {reason!r}"
    )
    assert uri in reason, (
        f"reason must reference the affected uri; got {reason!r}"
    )


def test_post_rejection_no_disk_write(
    calcpy_workspace: Path,
) -> None:
    """Belt-and-suspenders: when an edit is rejected by
    ``_check_apply_clean``, the caller (merge_and_validate) routes it
    to ``surfaced`` rather than ``auto_apply``. We simulate the
    contract here by:
    1. Detecting the rejection.
    2. Verifying the target file's bytes are unchanged.

    The pure-python invariant under test never touches disk — this
    test is a documented redundancy that asserts the helper's
    side-effect-free property holds for the canonical bytes-on-disk
    invariant the agent depends on."""
    from serena.refactoring.multi_server import _check_apply_clean

    # Use a real fixture file so the bytes-unchanged check is meaningful.
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    pre = src.read_bytes()
    uri = src.as_uri()
    edit = {
        "documentChanges": [_make_versioned_text_doc_edit(uri, version=1)],
    }
    document_versions = {uri: 99}
    ok, _ = _check_apply_clean(
        edit=edit,
        document_versions=document_versions,
    )
    assert ok is False, "stale-version edit must be rejected"
    post = src.read_bytes()
    assert post == pre, (
        "STALE_VERSION rejection must be side-effect-free; "
        "calcpy.py bytes changed despite reject path"
    )
