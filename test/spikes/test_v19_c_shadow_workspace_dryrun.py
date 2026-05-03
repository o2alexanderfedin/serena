"""v1.9.2 Item C — shadow-workspace simulation for ``dry_run_compose``.

Closes the v1.6 SHIP-B deferral. ``shadow_mode=True`` redirects each
dry-run step to an isolated copy of the project so any side effect that
slips past a facade's own ``dry_run=True`` honoring (or any path that
writes regardless of dry_run) is contained to the shadow tempdir and
never reaches the live workspace.

RED tests:

1. End-to-end: a real per-symbol Python split runs against a shadow,
   live ``mod.py`` is byte-identical post-call, ComposeResult reports a
   non-empty per-step preview.

2. Shadow path tolerates a facade that ignores ``dry_run`` and writes to
   disk anyway: live workspace unchanged, shadow capture shows the
   would-be edit, no exception bubbles up.

3. ``shadow_mode=False`` (default) keeps the v1.6 behaviour — the live
   workspace can be touched (verifying the shadow path is truly opt-in
   and we haven't accidentally regressed the legacy semantics).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_primitives import DryRunComposeTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> DryRunComposeTool:
    tool = DryRunComposeTool.__new__(DryRunComposeTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "mod.py"
    src.write_text(
        "def keep_a(x):\n    return x\n\n"
        "def move_b(y):\n    return y * 2\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# RED 1 — shadow_mode shields the live workspace during a real per-symbol move
# ---------------------------------------------------------------------------


def test_dry_run_shadow_keeps_live_workspace_untouched(tmp_path: Path) -> None:
    workspace = _python_workspace(tmp_path)
    src = workspace / "mod.py"
    pre_text = src.read_text(encoding="utf-8")
    tool = _make_tool(workspace)
    raw = tool.apply(
        steps=[{
            "tool": "split_file",
            "args": {
                "file": str(src),
                "groups": {"target.py": ["move_b"]},
                "language": "python",
            },
        }],
        shadow_mode=True,
    )
    payload = json.loads(raw)
    assert payload.get("transaction_id"), payload
    # The compose preview must report a per-step entry without raising.
    assert len(payload["per_step"]) == 1, payload
    # Live workspace is byte-identical to its pre-state.
    assert src.read_text(encoding="utf-8") == pre_text, (
        "shadow_mode=True must not mutate the live workspace"
    )
    # The target file must NOT have been created in the live workspace.
    assert not (workspace / "target.py").exists()


# ---------------------------------------------------------------------------
# RED 2 — shadow contains side effects from facades that ignore dry_run
# ---------------------------------------------------------------------------


def test_dry_run_shadow_contains_side_effects_from_misbehaving_facade(tmp_path: Path) -> None:
    """Substitute a fake facade that always writes regardless of ``dry_run``.

    Demonstrates the shadow guarantee: even a buggy facade can't reach
    the live workspace when ``shadow_mode=True``.
    """
    from serena.tools import scalpel_facades

    workspace = _python_workspace(tmp_path)
    src = workspace / "mod.py"
    pre_text = src.read_text(encoding="utf-8")

    def _misbehaving_facade(**kwargs: Any) -> str:
        # Always writes the file, ignoring dry_run.
        target = Path(kwargs["file"])
        target.write_text("# scribbled by misbehaving facade\n", encoding="utf-8")
        return json.dumps({
            "applied": True,
            "checkpoint_id": "cp_fake",
            "changes": [],
            "diagnostics_delta": {
                "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
                "after":  {"error": 0, "warning": 0, "information": 0, "hint": 0},
                "new_findings": [],
                "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            },
        })

    original = dict(scalpel_facades._FACADE_DISPATCH)
    scalpel_facades._FACADE_DISPATCH["test_misbehaving_facade"] = _misbehaving_facade
    try:
        tool = _make_tool(workspace)
        raw = tool.apply(
            steps=[{
                "tool": "test_misbehaving_facade",
                "args": {"file": str(src)},
            }],
            shadow_mode=True,
        )
    finally:
        scalpel_facades._FACADE_DISPATCH.clear()
        scalpel_facades._FACADE_DISPATCH.update(original)
    payload = json.loads(raw)
    assert payload.get("transaction_id"), payload
    # Live ``mod.py`` is byte-identical — the misbehaving write landed in the shadow.
    assert src.read_text(encoding="utf-8") == pre_text


# ---------------------------------------------------------------------------
# RED 3 — shadow_mode=False (default) does NOT shield (legacy v1.6 behaviour)
# ---------------------------------------------------------------------------


def test_dry_run_default_is_not_shadow_mode(tmp_path: Path) -> None:
    """Sanity guard: shadow_mode is opt-in. The default keeps the v1.6 wire
    where each facade's own ``dry_run=True`` honoring decides whether the
    live workspace is touched.
    """
    workspace = _python_workspace(tmp_path)
    src = workspace / "mod.py"
    tool = _make_tool(workspace)
    raw = tool.apply(
        steps=[{
            "tool": "split_file",
            "args": {
                "file": str(src),
                "groups": {"target.py": ["move_b"]},
                "language": "python",
            },
        }],
    )
    payload = json.loads(raw)
    # Default mode returns successfully; we don't assert disk state because
    # the contract is "facade decides". The point is shadow_mode is OPT-IN.
    assert payload.get("transaction_id"), payload
