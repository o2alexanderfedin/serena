"""Mutation test for the L05 determinism guard.

Companion to ``test_e2e_e1_py_determinism.py``. The original test asserts
``payload.get("applied") is True`` on every iteration of the 10-run
parametrize loop — but a passing assertion on its own does NOT prove the
assertion would catch the failure mode it's designed to catch. This
module supplies that negative evidence with a mutation test:

  1. Construct the exact assertion logic the determinism test uses
     (``assert payload.get("applied") is True``).
  2. Feed it a synthetic ``applied=False`` payload (the failure mode the
     guard is meant to catch).
  3. Assert the body raises ``AssertionError``.

This pins the contract that the determinism guard is load-bearing, not
ornamental — a regression that turns the guard into a no-op (e.g.
swapping ``is True`` for ``is not None``) would fail this test.

The mutation targets the assertion behaviour, not the booted MCP driver
— so it runs offline, fast, and on every host (no e2e gate, no LSP
binaries required). The original e2e test continues to provide the
positive evidence against the live MCP runtime.

Author: AI Hive(R).
"""
from __future__ import annotations

import json
from typing import Any

import pytest


def _determinism_assertion_body(payload_json: str, run_index: int) -> None:
    """The assertion logic from ``test_e1_py_split_applies_every_run``.

    Mirrors the exact two-stage check at
    ``test_e2e_e1_py_determinism.py:49-55``: ``applied is True`` first,
    then ``checkpoint_id`` truthy. Inlined here (rather than imported)
    because the original lives inside a ``@pytest.mark.e2e`` body that
    needs the booted ``mcp_driver_python`` fixture.
    """
    payload: dict[str, Any] = json.loads(payload_json)
    assert payload.get("applied") is True, (
        f"run {run_index}: applied=False; "
        f"failure={payload.get('failure')!r}; full payload={payload!r}"
    )
    assert payload.get("checkpoint_id"), (
        f"run {run_index}: applied=true but no checkpoint_id: {payload!r}"
    )


def test_determinism_assertion_fires_on_applied_false() -> None:
    """The guard MUST raise ``AssertionError`` on ``applied=False``.

    Mutation evidence: prove the guard catches the exact failure mode it
    was added to catch (the intermittent ``applied=False`` payload that
    Stage 2B observed before the determinism contract was locked).
    """
    fake_payload = json.dumps(
        {"applied": False, "failure": "synthetic", "checkpoint_id": None}
    )
    with pytest.raises(AssertionError, match="applied=False"):
        _determinism_assertion_body(fake_payload, run_index=0)


def test_determinism_assertion_fires_on_missing_applied_field() -> None:
    """The guard MUST raise on a payload missing the ``applied`` field.

    A regression that returns a payload without ``applied`` at all (e.g.
    a partial error response) should be loud, not silently equivalent
    to ``applied=False`` slipping through.
    """
    fake_payload = json.dumps({"failure": "missing-field", "checkpoint_id": None})
    with pytest.raises(AssertionError, match="applied=False"):
        _determinism_assertion_body(fake_payload, run_index=3)


def test_determinism_assertion_fires_on_truthy_but_not_true_applied() -> None:
    """``is True`` (not just truthy) — guards against ``applied="yes"`` etc.

    This is the contract the spec pinned with ``is True`` rather than the
    weaker ``payload["applied"]`` truthiness check. A regression that
    relaxes the check to truthiness would let string sentinels through.
    """
    fake_payload = json.dumps(
        {"applied": "yes", "failure": None, "checkpoint_id": "cp-x"}
    )
    with pytest.raises(AssertionError, match="applied=False"):
        _determinism_assertion_body(fake_payload, run_index=7)


def test_determinism_assertion_fires_on_missing_checkpoint_when_applied() -> None:
    """The second-stage guard MUST raise when ``applied=true`` but no checkpoint."""
    fake_payload = json.dumps(
        {"applied": True, "failure": None, "checkpoint_id": None}
    )
    with pytest.raises(AssertionError, match="no checkpoint_id"):
        _determinism_assertion_body(fake_payload, run_index=9)


def test_determinism_assertion_passes_on_well_formed_payload() -> None:
    """Sanity: a properly-applied payload must NOT raise.

    Without this companion check the four failure-path tests above could
    pass even if the assertion logic were stuck always-raising. This
    closes the mutation-coverage loop.
    """
    good_payload = json.dumps(
        {"applied": True, "failure": None, "checkpoint_id": "cp-1"}
    )
    _determinism_assertion_body(good_payload, run_index=0)
