"""B2.2 — SplitFileTool Python arm outcome assertion.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B2
regression: v1.6-stub-facade-fix-complete

Pre-v1.6, SplitFileTool's Python arm returned a success envelope
without writing the new split file to disk. This test asserts:

1. The envelope exposes real-work signals (not the bare
   ``{"status": "ok"}`` STUB pattern that existed pre-v1.6).
2. ``dry_run=True`` returns ``applied=False`` + a non-empty
   ``preview_token`` — confirming the facade reached the real branch,
   not an early-return stub.
3. ``dry_run=False`` returns ``applied=True`` + a non-empty
   ``checkpoint_id`` — confirming the facade actually applied the edit.

Design notes
------------
- ``SplitFileTool._split_python`` calls ``_build_python_rope_bridge``
  (a top-level function in ``scalpel_facades`` extracted precisely to
  be patchable — see its docstring). We inject a ``MagicMock`` bridge
  whose ``move_module`` returns a synthetic ``WorkspaceEdit`` so the
  test is self-contained with no pylsp/rope installed.
- Uses ``tmp_path`` (not the session ``calcpy_workspace`` fixture) to
  avoid shared-state mutation: the dry_run=False path writes to disk.
- Uses ``groups={"helpers": []}`` (empty symbol list) to trigger the
  ``move_module`` (whole-module-move) branch — the simplest path
  through ``_split_python``.
- Mirrors the construction pattern from PB11
  (``test_b1_facade_arg_validation.py``) and the spike that proved the
  fix (``test_v16_p3_split_python_apply.py``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Runtime isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    """Reset the ScalpelRuntime singleton around each test so checkpoint
    state and coordinator references do not bleed across tests."""
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(project_root: Path):  # type: ignore[return]
    """Construct SplitFileTool without going through __init__.

    Mirrors the pattern in test_b1_facade_arg_validation.py and the
    v1.6 spike tests.
    """
    from serena.tools.scalpel_facades import SplitFileTool
    tool = SplitFileTool.__new__(SplitFileTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _python_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal Python workspace and return (workspace, source_file)."""
    src = tmp_path / "calcpy.py"
    src.write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    return tmp_path, src


def _make_workspace_edit(uri: str) -> dict[str, Any]:
    """Build a WorkspaceEdit that replaces the first line so disk mutation
    is detectable."""
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


def _make_fake_bridge(uri: str) -> MagicMock:
    """Return a MagicMock rope bridge whose move_module returns a real edit."""
    fake = MagicMock()
    fake.move_module.return_value = _make_workspace_edit(uri)
    return fake


# ---------------------------------------------------------------------------
# B2.2 — dry_run=True: must return preview_token (not bare status=ok STUB)
# ---------------------------------------------------------------------------


@pytest.mark.python
def test_split_file_python_dry_run_returns_preview_token_not_stub(
    tmp_path: Path,
) -> None:
    """Post-v1.6, dry_run=True must return preview_token, not bare status=ok.

    Regression guard for the STUB fixed in v1.6-stub-facade-fix-complete:
    SplitFileTool._split_python previously returned {"status": "ok"} for
    the dry_run branch while leaving disk unchanged *and* without surfacing
    any real-work signals. Post-fix, the dry_run branch returns a
    RefactorResult with applied=False + a non-empty preview_token.

    Assertion hierarchy:
    1. Result must be valid JSON.
    2. MUST NOT be the bare STUB pattern (status=ok with ≤ 2 keys).
    3. MUST contain at least one real-work signal.
    4. In dry_run=True mode: applied=False AND non-empty preview_token.
    5. Disk MUST be untouched (no side effects).
    """
    workspace, src = _python_workspace(tmp_path)
    pre_edit = src.read_text(encoding="utf-8")
    uri = src.as_uri()
    tool = _make_tool(workspace)
    fake_bridge = _make_fake_bridge(uri)

    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        result_str = tool.apply(
            file=str(src),
            groups={"helpers": []},  # empty list → move_module branch
            language="python",
            dry_run=True,
        )

    # --- Must be valid JSON ---
    try:
        envelope = json.loads(result_str)
    except json.JSONDecodeError:
        pytest.fail(
            f"SplitFileTool.apply returned non-JSON: {result_str[:300]!r}"
        )

    # --- MUST NOT: bare STUB pattern ---
    is_bare_stub = (
        envelope.get("status") == "ok"
        and len(envelope) <= 2
        and "checkpoint_id" not in envelope
        and "preview_token" not in envelope
        and "applied" not in envelope
    )
    assert not is_bare_stub, (
        f"STUB regression: envelope matches the v1.6-bug fingerprint "
        f"(bare status=ok with no real-work signals): {envelope}"
    )

    # --- MUST: at least one real-work signal ---
    real_work_signals = {"preview_token", "checkpoint_id", "applied", "no_op"}
    found = real_work_signals & set(envelope.keys())
    assert found, (
        f"Envelope lacks real-work signals {real_work_signals!r} — "
        f"likely a STUB regression or unexpected shape.\nEnvelope: {envelope}"
    )

    # --- dry_run semantics: applied=False + non-empty preview_token ---
    assert envelope.get("applied") is False, (
        f"dry_run=True must not set applied=True: {envelope}"
    )
    preview_token = envelope.get("preview_token")
    assert preview_token, (
        f"dry_run=True must return a non-empty preview_token: {envelope}"
    )

    # --- No disk mutation ---
    assert src.read_text(encoding="utf-8") == pre_edit, (
        "dry_run=True must not mutate the source file"
    )


# ---------------------------------------------------------------------------
# B2.2 — dry_run=False: must return applied=True + checkpoint_id
# ---------------------------------------------------------------------------


@pytest.mark.python
def test_split_file_python_apply_returns_checkpoint_not_stub(
    tmp_path: Path,
) -> None:
    """Post-v1.6, dry_run=False must return applied=True + checkpoint_id.

    Regression guard: before the v1.6 fix, _split_python returned
    {"status": "ok"} without checkpointing or applying the workspace edit.
    Post-fix, it calls apply_workspace_edit_and_checkpoint and embeds the
    returned checkpoint_id in the RefactorResult.

    Assertion hierarchy:
    1. Result must be valid JSON.
    2. MUST NOT be the bare STUB pattern.
    3. applied=True.
    4. Non-empty checkpoint_id.
    5. Disk IS mutated (the fake bridge's WorkspaceEdit is applied).
    """
    workspace, src = _python_workspace(tmp_path)
    pre_edit = src.read_text(encoding="utf-8")
    uri = src.as_uri()
    tool = _make_tool(workspace)
    fake_bridge = _make_fake_bridge(uri)

    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        result_str = tool.apply(
            file=str(src),
            groups={"helpers": []},  # empty list → move_module branch
            language="python",
            dry_run=False,
        )

    # --- Must be valid JSON ---
    try:
        envelope = json.loads(result_str)
    except json.JSONDecodeError:
        pytest.fail(
            f"SplitFileTool.apply returned non-JSON: {result_str[:300]!r}"
        )

    # --- MUST NOT: bare STUB pattern ---
    is_bare_stub = (
        envelope.get("status") == "ok"
        and len(envelope) <= 2
        and "checkpoint_id" not in envelope
        and "applied" not in envelope
    )
    assert not is_bare_stub, (
        f"STUB regression: envelope matches the v1.6-bug fingerprint "
        f"(bare status=ok with no real-work signals): {envelope}"
    )

    # --- apply semantics: applied=True + checkpoint_id ---
    assert envelope.get("applied") is True, (
        f"dry_run=False + successful edit must set applied=True: {envelope}"
    )
    checkpoint_id = envelope.get("checkpoint_id")
    assert checkpoint_id, (
        f"dry_run=False must return a non-empty checkpoint_id: {envelope}"
    )

    # --- Disk IS mutated ---
    post_edit = src.read_text(encoding="utf-8")
    assert post_edit != pre_edit, (
        "dry_run=False must mutate the source file via the workspace edit"
    )
    assert post_edit.startswith("def aaa(): pass"), (
        f"Unexpected post-edit content: {post_edit[:80]!r}"
    )
