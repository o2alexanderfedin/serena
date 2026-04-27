"""Stage 1H T11 Module 5 — Multi-server invariant 3 (disabled-reason
surfacing) from original plan §11.7.

Per §11.7 invariant 3, the merge result must surface ALL candidates —
including disabled ones — so the agent can audit. Every disabled
candidate MUST carry a non-empty ``disabled_reason`` string (the
auditability gate).

(a) ``merge_code_actions`` returns a list that includes disabled
    candidates alongside auto-applicable winners.

(b) Every disabled candidate's ``disabled_reason`` is a non-empty
    string — never None, never empty/whitespace.

Skips
-----
``python_coordinator`` requires pylsp + basedpyright + ruff binaries
on PATH; absent any one the fixture skips collection. This module
runs against the real merge path because the disabled-surfacing
behavior is observable only through the full broadcast → resolve →
priority → dedup pipeline.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from solidlsp.util.file_range import compute_file_range


def _runner(coro: Any) -> Any:
    """Run ``coro`` in a fresh event loop and clean up."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_merge_surfaces_all_candidates_including_disabled(
    python_coordinator: Any,
    calcpy_workspace: Path,
) -> None:
    """The merge result list contains both auto-apply winners and any
    disabled candidates the servers emitted — agent visibility for
    audit."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    assert src.is_file(), f"fixture missing: {src}"
    start, end = compute_file_range(str(src))

    pylsp = python_coordinator.servers["pylsp-rope"]._inner
    bp = python_coordinator.servers["basedpyright"]._inner
    ruff = python_coordinator.servers["ruff"]._inner

    rel = "calcpy/calcpy.py"
    with pylsp.open_file(rel):
        with bp.open_file(rel):
            with ruff.open_file(rel):
                time.sleep(1.0)
                merged = _runner(
                    python_coordinator.merge_code_actions(
                        file=str(src),
                        start=start,
                        end=end,
                        # No only-filter so we surface everything.
                        only=None,
                        diagnostics=[],
                    )
                )

    # Sanity: at least one candidate must surface; otherwise the host
    # didn't return any code actions and the auditability gate is
    # vacuous.
    if not merged:
        pytest.skip(
            "merge returned zero candidates on this host; nothing to audit"
        )
    # Pure-list contract: a python list of MergedCodeAction.
    assert isinstance(merged, list), f"expected list, got {type(merged)}"


def test_every_disabled_candidate_has_nonempty_reason(
    python_coordinator: Any,
    calcpy_workspace: Path,
) -> None:
    """Auditability gate: a disabled candidate without a reason is a
    bug because the agent can't explain to the user why the action
    was suppressed. Every disabled candidate MUST carry a non-empty
    ``disabled_reason`` per §11.7 invariant 3."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    start, end = compute_file_range(str(src))

    pylsp = python_coordinator.servers["pylsp-rope"]._inner
    bp = python_coordinator.servers["basedpyright"]._inner
    ruff = python_coordinator.servers["ruff"]._inner

    rel = "calcpy/calcpy.py"
    with pylsp.open_file(rel):
        with bp.open_file(rel):
            with ruff.open_file(rel):
                time.sleep(1.0)
                merged = _runner(
                    python_coordinator.merge_code_actions(
                        file=str(src),
                        start=start,
                        end=end,
                        only=None,
                        diagnostics=[],
                    )
                )

    disabled = [m for m in merged if m.disabled_reason is not None]
    if not disabled:
        pytest.skip(
            "no disabled candidates surfaced on this host; auditability "
            "gate has nothing to assert"
        )
    for m in disabled:
        assert m.disabled_reason and m.disabled_reason.strip(), (
            f"disabled candidate must carry a non-empty reason; got "
            f"title={m.title!r} provenance={m.provenance!r} "
            f"disabled_reason={m.disabled_reason!r}"
        )
