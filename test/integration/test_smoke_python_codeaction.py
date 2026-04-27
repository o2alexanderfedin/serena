"""Stage 1H smoke 2 — ruff offers ``source.organizeImports.ruff`` on calcpy.

Proves the harness boots ruff against the calcpy fixture and that
ruff advertises ``source.organizeImports.ruff`` (or its un-suffixed
``source.organizeImports`` fallback) on the deliberately-unsorted
import block in ``calcpy/core.py``.

This exercises the multi-server-relevant code path because ruff ships
the ``.ruff`` suffix that Stage 1D's ``_normalize_kind`` collapses
onto the ``source.organizeImports`` priority family.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from solidlsp.util.file_range import compute_file_range


def test_ruff_offers_organize_imports_on_calcpy_core(
    ruff_lsp: Any,
    calcpy_workspace: Path,
) -> None:
    """ruff must surface ``source.organizeImports`` (any suffix) on core.py."""
    core_path = str(calcpy_workspace / "calcpy" / "core.py")
    assert Path(core_path).is_file(), f"fixture file missing: {core_path}"

    # ruff-server initialises quickly (no full project index) — 0.5 s
    # is enough for the LSP to be ready to answer codeAction.
    time.sleep(0.5)

    # Migrated from the ``whole_file_range`` fixture's legacy
    # unparametrized fallback (removed in stage-v0.2.0-review-i3).
    # ``compute_file_range`` returns the precise (start, end) pair.
    start, end = compute_file_range(core_path)
    actions: list[dict[str, Any]] = []
    with ruff_lsp.open_file("calcpy/core.py"):
        time.sleep(0.5)
        raw = ruff_lsp.request_code_actions(
            core_path,
            start=start,
            end=end,
            only=["source.organizeImports"],
            diagnostics=[],
        )
        actions.extend(a for a in raw if isinstance(a, dict))

    assert actions, (
        "ruff returned no actions for source.organizeImports filter on "
        "core.py — fixture imports may not be triggering the rule."
    )

    # LSP §3.18.1 prefix matching: a returned ``source.organizeImports``
    # or ``source.organizeImports.ruff`` both satisfy the family filter.
    kinds = [a.get("kind", "") for a in actions]
    matched = [
        k
        for k in kinds
        if k == "source.organizeImports" or k.startswith("source.organizeImports.")
    ]
    assert matched, (
        f"actions returned but none matched source.organizeImports family: {kinds!r}"
    )
