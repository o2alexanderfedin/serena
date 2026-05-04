"""B2.1 — apply_capability outcome-not-envelope assertion.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B2
regression: v1.6-stub-facade-fix-complete (parent d0a7a75d)

Pre-v1.6, apply_capability returned {"status": "ok"} while disk was
unchanged — a STUB lying to the LLM. Post-fix, _dispatch_via_coordinator
calls apply_action_and_checkpoint and returns a real checkpoint_id (on
apply) or a real preview_token (on dry_run). This integration test
exercises the live round-trip: real python_coordinator + real calcpy.py
file → envelope exposes genuine work-signal fields, not the bare
{"status": "ok"} fingerprint.

Design notes
------------
- Uses the real ``python_coordinator`` session fixture (pylsp-rope +
  basedpyright + ruff).  Skips cleanly when any binary is absent.
- Construction pattern mirrors PB11 (test_b1_facade_arg_validation.py):
  ``Tool.__new__(cls)`` + ``tool.get_project_root = lambda: ...``.
  Unlike the facade tools in scalpel_facades.py, ``ApplyCapabilityTool``
  is in scalpel_primitives.py and reaches the coordinator via
  ``ScalpelRuntime.instance().coordinator_for(...)``, so we patch
  ``ScalpelRuntime.coordinator_for`` to return the real fixture coordinator
  (same technique used by the v1.6 spike:
  test/spikes/test_v16_p2_apply_capability_dispatch.py).
- Uses ``dry_run=True`` to avoid mutating the shared session fixture files;
  the dry-run path still exercises the full dispatch up to (but not
  including) ``apply_action_and_checkpoint``.
- Primary assertion: the envelope must expose at least one of the
  real-work signals introduced by v1.6 (``checkpoint_id``,
  ``preview_token``, ``applied``, ``no_op``), and must NOT be the bare
  ``{"status": "ok"}`` stub.
- capability_id ``python.source.organizeImports`` (ruff server) is chosen
  because ruff is fast, side-effect-free on dry_run, and always present
  when the ruff fixture is available.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    """Reset the ScalpelRuntime singleton before/after each test so patching
    coordinator_for does not bleed across tests."""
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_tool(cls: type, project_root: Path) -> Any:
    """Construct a Tool subclass without going through __init__.

    Mirrors the pattern in test_b1_facade_arg_validation.py.
    """
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


# ---------------------------------------------------------------------------
# B2.1 test
# ---------------------------------------------------------------------------


@pytest.mark.python
def test_apply_capability_returns_real_envelope_post_v16(
    python_coordinator: Any,
    calcpy_workspace: Path,
) -> None:
    """Post-v1.6, dry_run envelope must carry preview_token (not bare status=ok).

    Regression guard for the STUB fixed in v1.6-stub-facade-fix-complete:
    ApplyCapabilityTool.apply previously returned {"status": "ok"} while
    leaving disk unchanged.  Post-fix, _dispatch_via_coordinator is wired
    to return a RefactorResult with real fields.

    Assertion hierarchy:
    1. MUST NOT: envelope is the bare stub pattern (status=ok, ≤ 2 keys).
    2. MUST: envelope contains at least one of the real-work signals:
       preview_token, checkpoint_id, applied, no_op.
    3. In dry_run=True mode the specific expected real signal is preview_token.
       If the capability is not available on this host's ruff server the
       dispatcher returns CAPABILITY_NOT_AVAILABLE (applied=False +
       failure.code) — that is an honest gap, not a STUB regression.
    """
    from serena.tools.scalpel_primitives import ApplyCapabilityTool

    target_file = calcpy_workspace / "calcpy" / "calcpy.py"
    assert target_file.is_file(), f"fixture file missing: {target_file}"

    # The capability_id for ruff's source.organizeImports (confirmed from the
    # baseline catalog: test/spikes/data/capability_catalog_baseline.json).
    capability_id = "python.source.organizeImports"

    tool = _make_tool(ApplyCapabilityTool, calcpy_workspace)

    # Patch ScalpelRuntime.coordinator_for to inject the real session fixture
    # coordinator. This mirrors the technique in:
    #   test/spikes/test_v16_p2_apply_capability_dispatch.py::_install_fake_coordinator
    # but provides the real MultiServerCoordinator instead of a _FakeCoordinator.
    with patch.object(
        ScalpelRuntime,
        "coordinator_for",
        return_value=python_coordinator,
    ):
        result_str = tool.apply(
            capability_id=capability_id,
            file=str(target_file),
            range_or_name_path={"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}},
            params=None,
            dry_run=True,  # avoid mutating shared session fixture files
        )

    # Result must be valid JSON.
    try:
        envelope = json.loads(result_str)
    except json.JSONDecodeError:
        pytest.fail(
            f"apply_capability returned non-JSON (unexpected raw text): "
            f"{result_str[:300]!r}"
        )

    # --- Primary regression assertion: NOT the bare stub pattern ---
    is_bare_stub = (
        envelope.get("status") == "ok"
        and len(envelope) <= 2
    )
    assert not is_bare_stub, (
        f"STUB regression: envelope matches the v1.6-bug fingerprint "
        f"(bare status=ok with ≤ 2 keys): {envelope}"
    )

    # --- Secondary assertion: at least one real-work signal present ---
    # The dispatcher always returns a RefactorResult pydantic model, which
    # serialises to JSON with these fields:
    #   applied (bool), no_op (bool|null), preview_token (str|null),
    #   checkpoint_id (str|null), failure (object|null), lsp_ops (list), ...
    # All are absent from the old {"status": "ok"} stub.
    real_work_signals = {"preview_token", "checkpoint_id", "applied", "no_op"}
    found_signals = real_work_signals & set(envelope.keys())
    assert found_signals, (
        f"Envelope lacks real-work signals {real_work_signals!r} — "
        f"likely a STUB regression or unexpected response shape.\n"
        f"Envelope: {envelope}"
    )

    # --- Tertiary assertion (dry_run path) ---
    # If the capability IS available, dry_run=True must yield preview_token
    # (not None) and applied=False (no disk write).
    if envelope.get("failure") is None:
        # No failure → the dispatcher reached the dry_run branch.
        assert envelope.get("applied") is False, (
            f"dry_run=True must not set applied=True: {envelope}"
        )
        preview_token = envelope.get("preview_token")
        assert preview_token, (
            f"dry_run=True must return a non-empty preview_token: {envelope}"
        )
    else:
        # CAPABILITY_NOT_AVAILABLE is an honest gap — skip with explanation.
        failure = envelope.get("failure", {})
        code = failure.get("code", "")
        if code == "CAPABILITY_NOT_AVAILABLE":
            pytest.skip(
                f"Capability {capability_id!r} not available on this host's "
                f"ruff server — CAPABILITY_NOT_AVAILABLE is honest, not a regression."
            )
        # Any other failure code is unexpected — surface it.
        pytest.fail(
            f"Unexpected failure in apply_capability (not a capability gap): "
            f"{envelope}"
        )
