"""T5 — DryRunComposeTool: shadow workspace, per-step delta, TTL."""

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


def _build_tool(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import DryRunComposeTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return DryRunComposeTool(agent=agent)


def test_tool_name_is_scalpel_dry_run_compose() -> None:
    from serena.tools.scalpel_primitives import DryRunComposeTool

    assert DryRunComposeTool.get_name_from_cls() == "dry_run_compose"


def test_apply_returns_transaction_id_and_5min_ttl(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply(steps=[])
    payload = json.loads(raw)
    assert "transaction_id" in payload
    assert payload["transaction_id"].startswith("txn_")
    now = time.time()
    assert now + 250 < payload["expires_at"] < now + 320


def test_apply_records_per_step_preview(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    steps_payload = [
        {"tool": "apply_capability",
         "args": {"capability_id": "x.unknown", "file": "a.py",
                  "range_or_name_path": "x"}},
    ]
    raw = tool.apply(steps=steps_payload)
    payload = json.loads(raw)
    assert len(payload["per_step"]) == 1
    assert payload["per_step"][0]["tool"] == "apply_capability"
    assert payload["per_step"][0]["step_index"] == 0


def _zero_diagnostics_dict() -> dict:
    zero = {"error": 0, "warning": 0, "information": 0, "hint": 0}
    return {
        "before": zero,
        "after": zero,
        "new_findings": [],
        "severity_breakdown": zero,
    }


def _ok_payload() -> str:
    return json.dumps({
        "applied": True, "no_op": False, "changes": [],
        "diagnostics_delta": _zero_diagnostics_dict(),
    })


def _failure_payload(reason: str, recoverable: bool = False) -> str:
    return json.dumps({
        "applied": False, "no_op": False, "changes": [],
        "diagnostics_delta": _zero_diagnostics_dict(),
        "failure": {
            "stage": "dry_run", "reason": reason,
            "code": "INTERNAL_ERROR", "recoverable": recoverable,
            "candidates": [],
        },
    })


def test_apply_fail_fast_default_aborts_at_first_failure(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    # Plan 4 (PR 5): drive _dry_run_one_step through real _FACADE_DISPATCH
    # rather than monkey-patching the function out. Each fake returns a
    # RefactorResult.model_dump_json() blob the body now projects.
    fake_ok = MagicMock(return_value=_ok_payload())
    fake_fail = MagicMock(return_value=_failure_payload("boom", recoverable=False))
    fake_never = MagicMock(return_value=_ok_payload())
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"ok_tool": fake_ok, "fail_tool": fake_fail, "never_run": fake_never},
        clear=False,
    ):
        raw = tool.apply(
            steps=[
                {"tool": "ok_tool", "args": {}},
                {"tool": "fail_tool", "args": {}},
                {"tool": "never_run", "args": {}},
            ],
            fail_fast=True,
        )
    payload = json.loads(raw)
    assert len(payload["per_step"]) == 2
    assert payload["per_step"][1]["failure"]["code"] == "INTERNAL_ERROR"
    assert any("TRANSACTION_ABORTED" in w for w in payload["warnings"])
    # Fail-fast: third facade must never be invoked.
    fake_never.assert_not_called()


def test_apply_fail_fast_false_continues_through_failures(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    fake_ok = MagicMock(return_value=_ok_payload())
    fake_fail = MagicMock(return_value=_failure_payload("boom", recoverable=True))
    fake_ok2 = MagicMock(return_value=_ok_payload())
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"ok": fake_ok, "fail": fake_fail, "ok2": fake_ok2},
        clear=False,
    ):
        raw = tool.apply(
            steps=[{"tool": "ok", "args": {}},
                   {"tool": "fail", "args": {}},
                   {"tool": "ok2", "args": {}}],
            fail_fast=False,
        )
    payload = json.loads(raw)
    assert len(payload["per_step"]) == 3
    # fail_fast=False: every facade is invoked even if middle one fails.
    fake_ok.assert_called_once()
    fake_fail.assert_called_once()
    fake_ok2.assert_called_once()


def test_apply_invalid_step_payload_returns_invalid_argument(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply(steps=[{"missing_tool_field": True}])  # type: ignore[arg-type]
    payload = json.loads(raw)
    assert "warnings" in payload
    assert any("INVALID_ARGUMENT" in w for w in payload["warnings"])
    assert payload["per_step"] == []
