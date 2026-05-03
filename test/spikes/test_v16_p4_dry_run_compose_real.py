"""v1.6 P4 — `_dry_run_one_step` calls real facade dispatch.

Plan 4 (PR 5) of `docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md`:
the previous body returned a hardcoded empty `StepPreview` regardless of `step.tool`,
which lied to the LLM. Post-fix: `_dry_run_one_step` looks up the facade in
`_FACADE_DISPATCH`, calls it with `args | {"dry_run": True}`, parses the resulting
`RefactorResult` payload, and projects it into `StepPreview.changes /
diagnostics_delta / failure`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _zero_diagnostics_delta_dict() -> dict:
    zero = {"error": 0, "warning": 0, "information": 0, "hint": 0}
    return {
        "before": zero,
        "after": zero,
        "new_findings": [],
        "severity_breakdown": zero,
    }


def _file_change_dict(path: str, kind: str = "modify") -> dict:
    return {
        "path": path,
        "kind": kind,
        "hunks": [{"start_line": 1, "end_line": 1, "new_text": "x"}],
        "provenance": {
            "source": "rust-analyzer",
            "workspace_boundary_check": True,
        },
    }


def _make_step(tool: str, args: dict | None = None):
    from serena.tools.scalpel_schemas import ComposeStep

    return ComposeStep(tool=tool, args=args or {})


# ---------------------------------------------------------------------------
# RED test 1 — facade returns non-empty changes => preview surfaces them
# ---------------------------------------------------------------------------


def test_dry_run_one_step_returns_changes_when_facade_returns_edit(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    payload = {
        "applied": True,
        "no_op": False,
        "changes": [_file_change_dict(str(tmp_path / "a.py"))],
        "diagnostics_delta": _zero_diagnostics_delta_dict(),
    }
    fake = MagicMock(return_value=json.dumps(payload))
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"fake_facade": fake},
        clear=False,
    ):
        preview = _dry_run_one_step(
            _make_step("fake_facade", {"file": "a.py"}),
            project_root=tmp_path,
            step_index=0,
        )
    assert preview.tool == "fake_facade"
    assert preview.changes != ()
    assert preview.changes[0].path == str(tmp_path / "a.py")
    assert preview.failure is None


# ---------------------------------------------------------------------------
# RED test 2 — facade returns failure => preview surfaces it
# ---------------------------------------------------------------------------


def test_dry_run_one_step_surfaces_failure_when_facade_fails(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    payload = {
        "applied": False,
        "no_op": False,
        "changes": [],
        "diagnostics_delta": _zero_diagnostics_delta_dict(),
        "failure": {
            "stage": "fake_facade",
            "reason": "synthetic boom",
            "code": "SYMBOL_NOT_FOUND",
            "recoverable": True,
            "candidates": [],
        },
    }
    fake = MagicMock(return_value=json.dumps(payload))
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"fake_facade": fake},
        clear=False,
    ):
        preview = _dry_run_one_step(
            _make_step("fake_facade"),
            project_root=tmp_path,
            step_index=2,
        )
    assert preview.failure is not None
    assert preview.failure.code.value == "SYMBOL_NOT_FOUND"
    assert preview.failure.reason == "synthetic boom"
    assert preview.step_index == 2


# ---------------------------------------------------------------------------
# RED test 3 — dispatch is called with args | {"dry_run": True}
# ---------------------------------------------------------------------------


def test_dry_run_one_step_uses_dry_run_true(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    payload = {
        "applied": True,
        "no_op": False,
        "changes": [],
        "diagnostics_delta": _zero_diagnostics_delta_dict(),
    }
    fake = MagicMock(return_value=json.dumps(payload))

    # Guarantee no disk writes by patching the disk-applier; if the body
    # ever forgets dry_run=True and the facade tries to write, the patch
    # will catch it.
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"fake_facade": fake},
        clear=False,
    ), patch(
        "serena.tools.facade_support._apply_workspace_edit_to_disk",
    ) as disk_apply:
        _dry_run_one_step(
            _make_step("fake_facade", {"file": "x.py", "name": "foo"}),
            project_root=tmp_path,
            step_index=0,
        )
    fake.assert_called_once()
    kwargs = fake.call_args.kwargs
    assert kwargs.get("dry_run") is True
    assert kwargs.get("file") == "x.py"
    assert kwargs.get("name") == "foo"
    disk_apply.assert_not_called()


# ---------------------------------------------------------------------------
# RED test 4 — diagnostics_delta from facade payload propagates into preview
# ---------------------------------------------------------------------------


def test_dry_run_one_step_diagnostics_delta_propagates(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    new_diag_delta = {
        "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        "after": {"error": 1, "warning": 0, "information": 0, "hint": 0},
        "new_findings": [
            {
                "file": str(tmp_path / "a.py"),
                "line": 3,
                "character": 4,
                "severity": 1,
                "code": "E0001",
                "message": "synthetic finding",
                "source": "rust-analyzer",
            }
        ],
        "severity_breakdown": {
            "error": 1, "warning": 0, "information": 0, "hint": 0,
        },
    }
    payload = {
        "applied": True,
        "no_op": False,
        "changes": [],
        "diagnostics_delta": new_diag_delta,
    }
    fake = MagicMock(return_value=json.dumps(payload))
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"fake_facade": fake},
        clear=False,
    ):
        preview = _dry_run_one_step(
            _make_step("fake_facade"),
            project_root=tmp_path,
            step_index=0,
        )
    assert preview.diagnostics_delta.after.error == 1
    assert len(preview.diagnostics_delta.new_findings) == 1
    assert preview.diagnostics_delta.new_findings[0].message == "synthetic finding"


# ---------------------------------------------------------------------------
# RED test 5 — CAPABILITY_NOT_AVAILABLE envelope passes through as warning
# ---------------------------------------------------------------------------


def test_dry_run_one_step_capability_not_available_envelope_passes_through(
    tmp_path: Path,
) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    payload = {
        "applied": False,
        "no_op": False,
        "changes": [],
        "diagnostics_delta": _zero_diagnostics_delta_dict(),
        "failure": {
            "stage": "fake_facade",
            "reason": "Pyright doesn't expose textDocument/implementation",
            "code": "CAPABILITY_NOT_AVAILABLE",
            "recoverable": True,
            "candidates": [],
        },
    }
    fake = MagicMock(return_value=json.dumps(payload))
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"fake_facade": fake},
        clear=False,
    ):
        preview = _dry_run_one_step(
            _make_step("fake_facade"),
            project_root=tmp_path,
            step_index=0,
        )
    assert preview.failure is not None
    assert preview.failure.code.value == "CAPABILITY_NOT_AVAILABLE"
    # Recoverable=True is the contract that the LLM may continue or fall back.
    assert preview.failure.recoverable is True


# ---------------------------------------------------------------------------
# RED test 6 — unknown tool returns INVALID_ARGUMENT failure
# ---------------------------------------------------------------------------


def test_dry_run_one_step_unknown_tool_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    # No registration in _FACADE_DISPATCH → INVALID_ARGUMENT failure.
    preview = _dry_run_one_step(
        _make_step("not_a_real_tool"),
        project_root=tmp_path,
        step_index=4,
    )
    assert preview.tool == "not_a_real_tool"
    assert preview.step_index == 4
    assert preview.failure is not None
    assert preview.failure.code.value == "INVALID_ARGUMENT"
    assert "not_a_real_tool" in preview.failure.reason


# ---------------------------------------------------------------------------
# RED test 7 — 5-min TTL regression guard
# ---------------------------------------------------------------------------


def test_dry_run_compose_5min_ttl_unchanged() -> None:
    from serena.tools.scalpel_primitives import DryRunComposeTool

    assert DryRunComposeTool.PREVIEW_TTL_SECONDS == 300


# ---------------------------------------------------------------------------
# RED test 8 — facade raises => preview surfaces INTERNAL_ERROR failure
# ---------------------------------------------------------------------------


def test_dry_run_one_step_handles_facade_exception(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _dry_run_one_step

    fake = MagicMock(side_effect=RuntimeError("synthetic crash"))
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"fake_facade": fake},
        clear=False,
    ):
        preview = _dry_run_one_step(
            _make_step("fake_facade"),
            project_root=tmp_path,
            step_index=1,
        )
    assert preview.failure is not None
    assert preview.failure.code.value == "INTERNAL_ERROR"
    assert "synthetic crash" in preview.failure.reason
