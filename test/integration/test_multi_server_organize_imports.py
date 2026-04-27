"""Stage 1H T11 Module 1 — Multi-server invariant 1 (priority) + invariant 3
(dedup) from original plan §11.7.

When pylsp + basedpyright + ruff all emit organize-imports candidates the
3-server merge must:

(a) surface exactly one applicable (non-disabled) survivor whose provenance
    is ``ruff`` (priority order ruff > basedpyright > pylsp-rope per
    ``_PRIORITY_TABLE`` for ``("source.organizeImports", None)``);
(b) surface losers (basedpyright / pylsp-rope) when those servers also
    proposed an organize-imports candidate, and any disabled losers must
    carry a non-empty ``disabled_reason`` (auditability gate).

Skips
-----
- ``python_coordinator`` requires pylsp + basedpyright + ruff binaries on
  PATH; if any is absent the fixture skips collection cleanly.
- When neither pylsp-rope nor ruff produces an organize-imports candidate
  on the host, the priority assertion is skipped with a clear reason
  (host-specific gap, not a merge regression).
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


def test_organize_imports_dedups_to_one_winner(
    python_coordinator: Any,
    calcpy_workspace: Path,
) -> None:
    """3-server merge yields exactly one applicable organize-imports
    candidate; provenance must be ``ruff`` per priority table."""
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
                        only=["source.organizeImports"],
                        diagnostics=[],
                    )
                )

    organize = [
        m for m in merged
        if (m.kind == "source.organizeImports"
            or m.kind.startswith("source.organizeImports.")
            or m.kind.startswith("source.organize_import"))
        and m.disabled_reason is None
    ]
    if not organize:
        kinds = [m.kind for m in merged]
        pytest.skip(
            f"no applicable organize-imports candidates returned by "
            f"3-server merge; kinds={kinds}"
        )
    # Stage-2 dedup contract: exactly one winner survives per family.
    assert len(organize) == 1, (
        f"expected exactly 1 applicable organize-imports survivor; got "
        f"{len(organize)}: titles="
        f"{[m.title for m in organize]} provenances="
        f"{[m.provenance for m in organize]}"
    )
    winner = organize[0]
    assert winner.provenance == "ruff", (
        f"expected ruff to win priority; got provenance="
        f"{winner.provenance!r} title={winner.title!r}"
    )


def test_organize_imports_disabled_losers_carry_reason(
    python_coordinator: Any,
    calcpy_workspace: Path,
) -> None:
    """Per §11.7 invariant 3 surfacing: any disabled organize-imports
    candidate the merge surfaces MUST have a non-empty
    ``disabled_reason``."""
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
                        only=["source.organizeImports"],
                        diagnostics=[],
                    )
                )

    losers = [
        m for m in merged
        if (m.kind == "source.organizeImports"
            or m.kind.startswith("source.organizeImports.")
            or m.kind.startswith("source.organize_import"))
        and m.disabled_reason is not None
    ]
    if not losers:
        pytest.skip(
            "no disabled organize-imports candidates surfaced on this host; "
            "auditability gate has nothing to assert"
        )
    for m in losers:
        assert m.disabled_reason and m.disabled_reason.strip(), (
            f"surfaced disabled candidate missing reason: title={m.title!r} "
            f"provenance={m.provenance!r} reason={m.disabled_reason!r}"
        )
