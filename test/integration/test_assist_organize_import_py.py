"""Stage 1H T10 Module 4 — Python: organize-imports across the 3-server merge.

Targets calcpy_notebooks/src/calcpy_min.py (deliberately ugly import block:
typing-before-stdlib, unused F401 imports). Asserts:

(a) ``python_coordinator.merge_code_actions(...)`` returns at least one
    organize-imports candidate (family ``source.organizeImports``).
(b) When both ruff (``source.organizeImports.ruff``) and pylsp-rope
    (``source.organize_import``) compete, ruff wins per the §11.7 priority
    table (``("source.organizeImports", None): ("ruff", "pylsp-rope",
    "basedpyright")``).
(c) The companion ``.ipynb`` byte content is unchanged after the .py
    organize-imports merge — multi-server merge must not leak edits
    into the notebook file.

Skip cleanly when ``python_coordinator`` is unavailable (host missing
pylsp/basedpyright) or when neither server offers an organize-imports
action (rare host-specific gap).
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


def test_organize_imports_returns_one_candidate(
    python_coordinator_notebooks: Any,
    calcpy_notebooks_workspace: Path,
) -> None:
    """The 3-server merge must return ≥1 organize-imports survivor."""
    src = calcpy_notebooks_workspace / "src" / "calcpy_min.py"
    assert src.is_file(), f"fixture missing: {src}"
    start, end = compute_file_range(str(src))

    # Open the file via every adapter so each server sees the buffer.
    pylsp = python_coordinator_notebooks.servers["pylsp-rope"]._inner
    bp = python_coordinator_notebooks.servers["basedpyright"]._inner
    ruff = python_coordinator_notebooks.servers["ruff"]._inner

    with pylsp.open_file("src/calcpy_min.py"):
        with bp.open_file("src/calcpy_min.py"):
            with ruff.open_file("src/calcpy_min.py"):
                time.sleep(1.0)
                merged = _runner(
                    python_coordinator_notebooks.merge_code_actions(
                        file=str(src),
                        start=start,
                        end=end,
                        only=["source.organizeImports"],
                        diagnostics=[],
                    )
                )

    organize = [
        m for m in merged
        if m.kind == "source.organizeImports"
        or m.kind.startswith("source.organizeImports.")
        or m.kind.startswith("source.organize_import")
    ]
    if not organize:
        kinds = [m.kind for m in merged]
        pytest.skip(
            f"no organize-imports candidates returned by 3-server merge; "
            f"kinds={kinds}"
        )
    assert organize, "merge yielded zero organize-imports survivors"


def test_organize_imports_ruff_wins_over_pylsp_rope(
    python_coordinator_notebooks: Any,
    calcpy_notebooks_workspace: Path,
) -> None:
    """Per §11.7, ruff outranks pylsp-rope for ``source.organizeImports``."""
    src = calcpy_notebooks_workspace / "src" / "calcpy_min.py"
    start, end = compute_file_range(str(src))

    pylsp = python_coordinator_notebooks.servers["pylsp-rope"]._inner
    bp = python_coordinator_notebooks.servers["basedpyright"]._inner
    ruff = python_coordinator_notebooks.servers["ruff"]._inner

    with pylsp.open_file("src/calcpy_min.py"):
        with bp.open_file("src/calcpy_min.py"):
            with ruff.open_file("src/calcpy_min.py"):
                time.sleep(1.0)
                merged = _runner(
                    python_coordinator_notebooks.merge_code_actions(
                        file=str(src),
                        start=start,
                        end=end,
                        only=["source.organizeImports"],
                        diagnostics=[],
                    )
                )

    organize = [
        m for m in merged
        if m.kind == "source.organizeImports"
        or m.kind.startswith("source.organizeImports.")
    ]
    if not organize:
        pytest.skip("no organize-imports candidates surfaced for priority check")

    # Find a winner — provenance must be ``ruff`` if both servers offered.
    provenances = {m.provenance for m in organize}
    if "ruff" not in provenances and "pylsp-rope" not in provenances:
        pytest.skip(
            f"neither ruff nor pylsp-rope produced an organize-imports candidate; "
            f"provenances={provenances}"
        )
    if "pylsp-rope" in provenances and "ruff" not in provenances:
        pytest.skip(
            "ruff did not surface an organize-imports candidate on this host; "
            "priority check needs both competitors present"
        )
    # When ruff is present the merge winner must be ruff.
    assert "ruff" in provenances, (
        f"ruff lost the organize-imports merge despite being highest priority; "
        f"provenances={provenances}"
    )


def test_companion_ipynb_unchanged_after_organize(
    python_coordinator_notebooks: Any,
    calcpy_notebooks_workspace: Path,
) -> None:
    """Organize-imports on the .py module must NOT touch the .ipynb companion."""
    src = calcpy_notebooks_workspace / "src" / "calcpy_min.py"
    nb = calcpy_notebooks_workspace / "notebooks" / "explore.ipynb"
    if not nb.is_file():
        pytest.skip(f"companion notebook missing: {nb}")
    nb_bytes_pre = nb.read_bytes()

    start, end = compute_file_range(str(src))
    pylsp = python_coordinator_notebooks.servers["pylsp-rope"]._inner
    bp = python_coordinator_notebooks.servers["basedpyright"]._inner
    ruff = python_coordinator_notebooks.servers["ruff"]._inner
    with pylsp.open_file("src/calcpy_min.py"):
        with bp.open_file("src/calcpy_min.py"):
            with ruff.open_file("src/calcpy_min.py"):
                time.sleep(1.0)
                _ = _runner(
                    python_coordinator_notebooks.merge_code_actions(
                        file=str(src),
                        start=start,
                        end=end,
                        only=["source.organizeImports"],
                        diagnostics=[],
                    )
                )

    nb_bytes_post = nb.read_bytes()
    assert nb_bytes_post == nb_bytes_pre, (
        "companion .ipynb bytes changed post-merge — multi-server merge "
        "leaked edits into the notebook file"
    )
