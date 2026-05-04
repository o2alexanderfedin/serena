"""B2.3 — DryRunComposeTool auto-mode outcome assertion.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B2
regression: v1.6-stub-facade-fix-complete

Pre-v1.6, ``dry_run_one_step`` (now called inside ``DryRunComposeTool.apply``)
returned a hardcoded empty ``StepPreview`` regardless of the step's tool, and
the auto-mode path did NOT create a real transaction — it returned
``awaiting_confirmation=True`` as if every call were ``confirmation_mode='manual'``.

Post-fix (v1.6):
- ``confirmation_mode='auto'`` (the default) takes the real path through
  ``txn_store.begin()`` and ``txn_store.add_step()``, returning a
  ``ComposeResult`` with ``transaction_id``, ``expires_at`` (in the future),
  and ``per_step``.
- ``confirmation_mode='manual'`` is the *only* path that sets
  ``awaiting_confirmation=True``.

This file contains two tests:

B2.3a — auto mode must NOT return ``awaiting_confirmation=True`` and MUST
         return a ComposeResult with a non-empty ``transaction_id`` and a
         positive ``expires_at`` in the future.

B2.3b — manual mode MUST return ``awaiting_confirmation=True``.  This is
         the counter-assertion that proves the two branches are distinct and
         neither regresses into the other.

Design notes
------------
- Uses ``DryRunComposeTool.__new__`` + ``tool.get_project_root = lambda: ...``
  (the same pattern as PB11/B2.1/B2.2).
- ``DryRunComposeTool.apply`` calls ``ScalpelRuntime.instance()`` directly
  (not ``coordinator_for``).  We reset the singleton before each test via the
  ``_isolate_runtime`` autouse fixture.  The tool's internal facade dispatch
  (``_dry_run_one_step``) is patched via ``_FACADE_DISPATCH`` to return a
  synthetic successful ``RefactorResult`` payload — so the test is
  self-contained with no LSP/language-server required.
- No ``@pytest.mark.python`` needed: no real coordinator is used.
- The fake step uses a synthetic tool name registered into ``_FACADE_DISPATCH``
  for the duration of the test; the step args are minimal.
- ``expires_at`` semantics: ``ComposeResult.expires_at`` is a wall-clock float
  (``time.time() + PREVIEW_TTL_SECONDS``).  We assert it is greater than
  ``time.time()`` at the point of the assertion (allowing up to 1 s of slack
  for slow CI).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Runtime isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    """Reset the ScalpelRuntime singleton before/after each test so transaction
    store state does not bleed across tests."""
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(project_root: Path):
    """Construct DryRunComposeTool without going through __init__.

    Mirrors the pattern in test_b2_apply_capability_outcome.py and
    test_b2_split_file_python_outcome.py.
    """
    from serena.tools.scalpel_primitives import DryRunComposeTool
    tool = DryRunComposeTool.__new__(DryRunComposeTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _zero_diagnostics_delta_dict() -> dict:
    zero = {"error": 0, "warning": 0, "information": 0, "hint": 0}
    return {
        "before": zero,
        "after": zero,
        "new_findings": [],
        "severity_breakdown": zero,
    }


def _fake_facade_payload() -> str:
    """Return a minimal valid RefactorResult JSON that _dry_run_one_step accepts."""
    return json.dumps({
        "applied": True,
        "no_op": False,
        "changes": [],
        "diagnostics_delta": _zero_diagnostics_delta_dict(),
    })


def _one_step(tool_name: str) -> dict:
    """Build a minimal ComposeStep dict for the given tool name."""
    return {"tool": tool_name, "args": {}}


# ---------------------------------------------------------------------------
# B2.3a — auto mode: must NOT set awaiting_confirmation=True
# ---------------------------------------------------------------------------


def test_dry_run_compose_auto_mode_returns_transaction_not_awaiting(
    tmp_path: Path,
) -> None:
    """Auto mode must return a real ComposeResult, NOT awaiting_confirmation.

    Regression guard for the v1.6 STUB fingerprint where the auto-mode path
    was aliased to the manual-mode path and returned
    ``awaiting_confirmation=True`` without creating a real transaction.

    Assertion hierarchy:
    1. Result must be valid JSON.
    2. MUST NOT contain ``awaiting_confirmation=True`` (the STUB fingerprint).
    3. MUST contain ``transaction_id`` (non-empty string).
    4. MUST contain ``expires_at`` as a positive float in the future.
    5. MUST contain ``per_step`` (a list, possibly empty if the fake step
       is unregistered — the step is registered via _FACADE_DISPATCH patch).
    """
    tool = _make_tool(tmp_path)
    fake = MagicMock(return_value=_fake_facade_payload())

    with patch.dict(
        "serena.tools.scalpel_facades._FACADE_DISPATCH",
        {"_b23_fake_tool": fake},
        clear=False,
    ):
        result_str = tool.apply(
            steps=[_one_step("_b23_fake_tool")],
            fail_fast=True,
            confirmation_mode="auto",
        )

    # --- Must be valid JSON ---
    try:
        envelope = json.loads(result_str)
    except json.JSONDecodeError:
        pytest.fail(
            f"DryRunComposeTool.apply returned non-JSON: {result_str[:300]!r}"
        )

    # --- MUST NOT: STUB fingerprint ---
    if envelope.get("awaiting_confirmation") is True:
        pytest.fail(
            f"STUB regression: auto mode returned awaiting_confirmation=True "
            f"(the v1.6 pre-fix fingerprint); manual mode is the only path "
            f"that should set this field.\nEnvelope: {envelope}"
        )

    # --- MUST: real ComposeResult fields ---
    txn_id = envelope.get("transaction_id")
    assert txn_id, (
        f"auto mode must return a non-empty transaction_id.\nEnvelope: {envelope}"
    )
    assert isinstance(txn_id, str), (
        f"transaction_id must be a string, got {type(txn_id)!r}.\nEnvelope: {envelope}"
    )

    expires_at = envelope.get("expires_at")
    assert expires_at is not None, (
        f"auto mode must return expires_at.\nEnvelope: {envelope}"
    )
    now = time.time()
    assert float(expires_at) > now - 1.0, (
        f"expires_at={expires_at} must be in the future (now={now}).\n"
        f"Envelope: {envelope}"
    )

    assert "per_step" in envelope, (
        f"ComposeResult must contain per_step.\nEnvelope: {envelope}"
    )
    assert isinstance(envelope["per_step"], list), (
        f"per_step must be a list.\nEnvelope: {envelope}"
    )


# ---------------------------------------------------------------------------
# B2.3b — manual mode: MUST set awaiting_confirmation=True (counter-assertion)
# ---------------------------------------------------------------------------


def test_dry_run_compose_manual_mode_returns_awaiting_confirmation(
    tmp_path: Path,
) -> None:
    """Manual mode must set awaiting_confirmation=True.

    Counter-assertion: this confirms the two branches (auto vs manual) are
    distinct and that the auto-mode fix did not accidentally suppress the
    manual-mode behaviour.

    Assertion:
    1. Result must be valid JSON.
    2. MUST contain ``awaiting_confirmation=True``.
    3. MUST contain ``transaction_id`` (manual mode also begins a transaction).
    """
    tool = _make_tool(tmp_path)

    # manual mode ignores steps entirely — it only uses workspace_edit.
    result_str = tool.apply(
        steps=[],
        fail_fast=True,
        confirmation_mode="manual",
        workspace_edit={},
    )

    # --- Must be valid JSON ---
    try:
        envelope = json.loads(result_str)
    except json.JSONDecodeError:
        pytest.fail(
            f"DryRunComposeTool.apply (manual) returned non-JSON: "
            f"{result_str[:300]!r}"
        )

    # --- MUST: awaiting_confirmation=True ---
    assert envelope.get("awaiting_confirmation") is True, (
        f"manual mode must set awaiting_confirmation=True.\nEnvelope: {envelope}"
    )

    # --- MUST: non-empty transaction_id ---
    txn_id = envelope.get("transaction_id")
    assert txn_id, (
        f"manual mode must return a non-empty transaction_id.\nEnvelope: {envelope}"
    )
