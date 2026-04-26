"""T6 — ScalpelRollbackTool + ScalpelTransactionRollbackTool: idempotent undo."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_single(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import ScalpelRollbackTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ScalpelRollbackTool(agent=agent)


def _build_multi(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import ScalpelTransactionRollbackTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ScalpelTransactionRollbackTool(agent=agent)


def test_tool_names() -> None:
    from serena.tools.scalpel_primitives import (
        ScalpelRollbackTool,
        ScalpelTransactionRollbackTool,
    )

    assert ScalpelRollbackTool.get_name_from_cls() == "scalpel_rollback"
    assert ScalpelTransactionRollbackTool.get_name_from_cls() == "scalpel_transaction_rollback"


def test_single_rollback_unknown_id_returns_no_op(tmp_path: Path) -> None:
    tool = _build_single(tmp_path)
    raw = tool.apply(checkpoint_id="ckpt_does_not_exist")
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["no_op"] is True
    assert payload.get("failure") is None  # idempotent unknown id


def test_single_rollback_known_id_invokes_restore(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    rt = ScalpelRuntime.instance()
    cid = rt.checkpoint_store().record(
        applied={"changes": {}}, snapshot={},
    )
    tool = _build_single(tmp_path)
    raw = tool.apply(checkpoint_id=cid)
    payload = json.loads(raw)
    # Restore returned False (n=0 ops applied) — surfaces as no_op.
    assert payload["no_op"] is True
    assert payload["applied"] is False
    assert payload.get("failure") is None


def test_single_rollback_idempotent_second_call(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    cid = ScalpelRuntime.instance().checkpoint_store().record(
        applied={"changes": {}}, snapshot={},
    )
    tool = _build_single(tmp_path)
    raw_a = tool.apply(checkpoint_id=cid)
    raw_b = tool.apply(checkpoint_id=cid)
    payload_a = json.loads(raw_a)
    payload_b = json.loads(raw_b)
    assert payload_a["no_op"] is True
    assert payload_b["no_op"] is True


def test_transaction_rollback_walks_in_reverse(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    rt = ScalpelRuntime.instance()
    txn_id = rt.transaction_store().begin()
    cid_a = rt.checkpoint_store().record(applied={"changes": {}}, snapshot={})
    cid_b = rt.checkpoint_store().record(applied={"changes": {}}, snapshot={})
    rt.transaction_store().add_checkpoint(txn_id, cid_a)
    rt.transaction_store().add_checkpoint(txn_id, cid_b)

    tool = _build_multi(tmp_path)
    raw = tool.apply(transaction_id=txn_id)
    payload = json.loads(raw)
    assert payload["transaction_id"] == txn_id
    assert payload["rolled_back"] is True
    assert len(payload["per_step"]) == 2


def test_transaction_rollback_unknown_txn_returns_no_op(tmp_path: Path) -> None:
    tool = _build_multi(tmp_path)
    raw = tool.apply(transaction_id="txn_does_not_exist")
    payload = json.loads(raw)
    assert payload["transaction_id"] == "txn_does_not_exist"
    assert payload["rolled_back"] is False
    assert payload["per_step"] == []
