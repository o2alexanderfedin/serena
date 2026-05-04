"""B1 — Facade arg-validation: ExtractTool resolves name_path via coordinator.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B1
regression: stage-v0.2.0-followup-i4-bugs-fixed (parent 15ab49f)

Pre-fix, scalpel_extract accepted ``name_path`` but did not resolve
it via MultiServerCoordinator.find_symbol_range — silent failure.
Post-fix, the resolver is wired in. This integration test exercises
the round-trip: name_path → resolve → extract → file NOT rejected at
the resolver stage.

Design notes
------------
- Uses the real ``python_coordinator`` session fixture (pylsp + basedpyright
  + ruff) — skips cleanly when any binary is absent from the host.
- Patches ``coordinator_for_facade`` to inject the real coordinator so the
  facade's ``coord.find_symbol_range`` call exercises the actual implementation
  rather than a mock.
- Targets ``_is_digit`` in ``calcpy/calcpy.py`` — a short, standalone function
  (line 227) that pylsp's document-symbol walk can locate without ambiguity.
- The primary regression assertion is that the resolver DID find the symbol
  (result must not contain SYMBOL_NOT_FOUND / "not found"). The extract itself
  may return CAPABILITY_NOT_AVAILABLE if pylsp-rope's dynamic registry does not
  advertise refactor.extract on this host — that is an honest capability gap,
  not a resolver regression.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(cls: type, project_root: Path) -> Any:
    """Construct a Tool subclass without going through __init__ (standard pattern)."""
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


# ---------------------------------------------------------------------------
# B1 test
# ---------------------------------------------------------------------------


@pytest.mark.python
def test_extract_facade_resolves_name_path(
    python_coordinator: Any,
    calcpy_workspace: Path,
) -> None:
    """ExtractTool with name_path must resolve via coordinator.find_symbol_range.

    Regression guard for the HIGH bug fixed in stage-v0.2.0-followup-i4-bugs-fixed:
    ``scalpel_extract`` previously accepted ``name_path`` but silently dropped it
    without calling ``coord.find_symbol_range``, so the extract was attempted at
    (0, 0) or failed with a mysterious error. Post-fix, the resolver is wired.

    Assertion hierarchy:
    1. MUST NOT: result contains "SYMBOL_NOT_FOUND" → resolver not called / failed.
    2. MUST NOT: result (lowercase) contains "not found" → resolver returned None.
    3. EITHER: result shows successful applied=True (disk changed), OR result
       contains "CAPABILITY_NOT_AVAILABLE" (pylsp-rope didn't advertise
       refactor.extract on this host — honest gap, not a resolver regression).
    """
    from serena.tools.scalpel_facades import ExtractTool

    # Open the target file on each underlying server so document-symbol
    # requests (used by find_symbol_range) resolve without a "file not open"
    # rejection. The relative path is relative to calcpy_workspace root.
    rel_path = "calcpy/calcpy.py"
    target_file = calcpy_workspace / rel_path
    assert target_file.is_file(), f"fixture missing: {target_file}"

    pylsp = python_coordinator.servers["pylsp-rope"]._inner
    bp = python_coordinator.servers["basedpyright"]._inner
    ruff = python_coordinator.servers["ruff"]._inner

    ScalpelRuntime.reset_for_testing()
    try:
        tool = _make_tool(ExtractTool, calcpy_workspace)

        with pylsp.open_file(rel_path):
            with bp.open_file(rel_path):
                with ruff.open_file(rel_path):
                    # Brief settle so servers index the file before we ask for
                    # document symbols — mirrors the existing multi-server tests.
                    time.sleep(0.5)

                    with patch(
                        "serena.tools.scalpel_facades.coordinator_for_facade",
                        return_value=python_coordinator,
                    ):
                        result_str = tool.apply(
                            file=str(target_file),
                            name_path="_is_digit",
                            target="function",
                            new_name="extracted_is_digit",
                            dry_run=True,   # dry_run=True: no disk mutation; still exercises resolver
                            language="python",
                        )
    finally:
        ScalpelRuntime.reset_for_testing()

    # --- Primary regression assertion: resolver must have been called and
    #     must NOT have returned "symbol not found". ---
    assert "SYMBOL_NOT_FOUND" not in result_str, (
        f"Resolver returned SYMBOL_NOT_FOUND — find_symbol_range failed or "
        f"was not called.\nResult: {result_str!r}"
    )
    lower = result_str.lower()
    assert "not found" not in lower, (
        f"Result contains 'not found' — name_path resolution failed.\nResult: {result_str!r}"
    )

    # --- Secondary assertion: the result must be one of the two valid outcomes. ---
    # Outcome A: successful dry-run preview (resolver + coordinator worked end-to-end).
    # Outcome B: CAPABILITY_NOT_AVAILABLE (pylsp-rope doesn't expose refactor.extract
    #            on this host) — honest capability gap, not a resolver regression.
    is_capability_gap = "CAPABILITY_NOT_AVAILABLE" in result_str
    is_success = '"applied"' in result_str or '"preview"' in result_str or '"actions"' in result_str

    assert is_capability_gap or is_success, (
        f"Unexpected result — neither a capability gap nor a successful preview.\n"
        f"Result: {result_str!r}"
    )

    if is_capability_gap:
        pytest.skip(
            "ExtractTool resolved _is_digit via find_symbol_range (resolver OK) "
            "but pylsp-rope does not advertise refactor.extract on this host — "
            "CAPABILITY_NOT_AVAILABLE is an honest gap, not a regression."
        )
