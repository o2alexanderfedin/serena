"""E2E scenario E11 — workspace-boundary refusal.

Maps to scope-report S15.1 row E11 and S11.8 (path-filter contract).
The atomic-rejection rule: a refactor on an out-of-workspace source
file is rejected by the boundary guard before any LSP / Rope traffic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


@pytest.mark.e2e
def test_e11_split_to_outside_workspace_path_rejected(
    mcp_driver_python,
    calcpy_e2e_root: Path,
    tmp_path: Path,
    wall_clock_record,
) -> None:
    """A split where the source `file=` is OUTSIDE the project root is
    rejected with WORKSPACE_BOUNDARY_VIOLATION before any Rope traffic.
    """
    del wall_clock_record
    in_src = calcpy_e2e_root / "calcpy" / "calcpy.py"
    pre_sha = _file_sha(in_src)

    # Source file lives outside the workspace -> the facade's
    # workspace_boundary_guard fires synchronously before any LSP call.
    outside_src = tmp_path / "outside_workspace" / "elsewhere.py"
    outside_src.parent.mkdir(parents=True, exist_ok=True)
    outside_src.write_text("def foo():\n    return 0\n")

    result_json = mcp_driver_python.split_file(
        file=str(outside_src),
        groups={"a": ["foo"]},
        parent_layout="file",
        dry_run=False,
        language="python",
        allow_out_of_workspace=False,
    )
    payload = json.loads(result_json)

    assert payload.get("applied") is False, (
        f"out-of-workspace split must NOT apply: {payload}"
    )
    failure = payload.get("failure") or {}
    code = failure.get("code", "")
    # WORKSPACE_BOUNDARY_VIOLATION is the canonical Stage 1G ErrorCode
    # for this case (scope-report's OUT_OF_WORKSPACE_EDIT_BLOCKED is the
    # historical alias).
    assert code in (
        "WORKSPACE_BOUNDARY_VIOLATION",
        "OUT_OF_WORKSPACE_EDIT_BLOCKED",
    ), f"expected workspace-boundary error; got {code!r}: {payload}"
    assert failure.get("recoverable") is False
    # In-workspace file untouched (atomic reject).
    assert _file_sha(in_src) == pre_sha, (
        "in-workspace file was modified despite reject"
    )


@pytest.mark.e2e
def test_e11_in_workspace_path_not_rejected_by_boundary(
    mcp_driver_python,
    calcpy_e2e_root: Path,
) -> None:
    """In-workspace dry-run is NOT rejected by the boundary guard.
    (The downstream Rope move may still fail or no-op for unsupported
    group shapes — that is unrelated to E11's contract.)
    """
    src = calcpy_e2e_root / "calcpy" / "calcpy.py"

    result_json = mcp_driver_python.split_file(
        file=str(src),
        groups={"ast": ["Num"]},
        parent_layout="file",
        dry_run=True,
        language="python",
        allow_out_of_workspace=False,
    )
    payload = json.loads(result_json)
    failure = payload.get("failure")
    if failure is not None:
        code = failure.get("code", "")
        assert code not in (
            "WORKSPACE_BOUNDARY_VIOLATION",
            "OUT_OF_WORKSPACE_EDIT_BLOCKED",
        ), (
            f"in-workspace dry-run incorrectly tripped boundary guard: "
            f"{failure}"
        )
