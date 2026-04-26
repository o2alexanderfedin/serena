"""Stage 2A T8 — ScalpelTransactionCommitTool tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelTransactionCommitTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> ScalpelTransactionCommitTool:
    tool = ScalpelTransactionCommitTool.__new__(ScalpelTransactionCommitTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_commit_unknown_transaction_returns_invalid_argument(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(transaction_id="txn_does-not-exist")
    payload = json.loads(out)
    assert payload["rolled_back"] is False
    assert any(
        "INVALID_ARGUMENT" in step["failure"]["code"]
        for step in payload["per_step"]
    ) or payload["per_step"] == []


def test_commit_replays_all_steps(tmp_path):
    runtime = ScalpelRuntime.instance()
    txn_store = runtime.transaction_store()
    raw_id = txn_store.begin()
    txn_store.add_step(raw_id, {"tool": "scalpel_extract",
                                "args": {"file": str(tmp_path / "x.py"),
                                         "target": "function"}})
    txn_store.add_step(raw_id, {"tool": "scalpel_inline",
                                "args": {"file": str(tmp_path / "x.py"),
                                         "target": "call"}})
    tool = _make_tool(tmp_path)
    fake_extract = MagicMock(return_value=json.dumps(
        {"applied": True, "no_op": False, "checkpoint_id": "cp_a",
         "diagnostics_delta": {
             "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
             "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
             "new_findings": [],
             "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
         }}
    ))
    fake_inline = MagicMock(return_value=json.dumps(
        {"applied": True, "no_op": False, "checkpoint_id": "cp_b",
         "diagnostics_delta": {
             "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
             "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
             "new_findings": [],
             "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
         }}
    ))
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"scalpel_extract": fake_extract, "scalpel_inline": fake_inline},
        clear=False,
    ):
        out = tool.apply(transaction_id=f"txn_{raw_id}")
    payload = json.loads(out)
    assert len(payload["per_step"]) == 2
    assert all(s["applied"] for s in payload["per_step"])
    assert payload["transaction_id"] == f"txn_{raw_id}"


def test_commit_first_failing_step_aborts(tmp_path):
    runtime = ScalpelRuntime.instance()
    txn_store = runtime.transaction_store()
    raw_id = txn_store.begin()
    txn_store.add_step(raw_id, {"tool": "scalpel_extract",
                                "args": {"file": str(tmp_path / "x.py"),
                                         "target": "function"}})
    txn_store.add_step(raw_id, {"tool": "scalpel_inline",
                                "args": {"file": str(tmp_path / "x.py"),
                                         "target": "call"}})
    tool = _make_tool(tmp_path)
    failing = MagicMock(return_value=json.dumps(
        {"applied": False, "no_op": False, "checkpoint_id": None,
         "diagnostics_delta": {
             "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
             "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
             "new_findings": [],
             "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
         },
         "failure": {"stage": "x", "reason": "boom",
                     "code": "SYMBOL_NOT_FOUND", "recoverable": True,
                     "candidates": []}}
    ))
    second = MagicMock()
    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"scalpel_extract": failing, "scalpel_inline": second},
        clear=False,
    ):
        out = tool.apply(transaction_id=f"txn_{raw_id}")
    payload = json.loads(out)
    assert len(payload["per_step"]) == 1
    assert payload["per_step"][0]["applied"] is False
    second.assert_not_called()


def test_commit_preview_expired(tmp_path):
    runtime = ScalpelRuntime.instance()
    txn_store = runtime.transaction_store()
    raw_id = txn_store.begin()
    # Insert a step so the empty-steps short-circuit doesn't fire first.
    txn_store.add_step(raw_id, {"tool": "scalpel_extract", "args": {}})
    txn_store.set_expires_at(raw_id, 1.0)  # always-past
    tool = _make_tool(tmp_path)
    out = tool.apply(transaction_id=f"txn_{raw_id}")
    payload = json.loads(out)
    assert payload["rolled_back"] is False
    assert any(
        s["failure"]["code"] == "PREVIEW_EXPIRED" for s in payload["per_step"]
    )
